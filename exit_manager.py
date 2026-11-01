import asyncio
import time
from typing import Dict, Any
import config
from binance_client import binance_client
from tracker import portfolio

class ExitManager:
    """
    Асимметричный трендовый менеджер выхода (Rocket Hunter Exit Engine — LONG & SHORT):
      1. Честный структурный стоп до TP1 — никаких ранних поджимов, выбивающих шумом.
      2. TP1 (+1.5R): фиксация ТОЛЬКО 30% позиции (окупает комиссии и фиксирует базовый плюс),
         перенос стопа оставшихся 70% в безубыток +0.20% (сделка становится безрисковой!).
      3. TP2 (+3.0R): фиксация еще 30% от начального объема (42.86% от остатка), заморозка +1.2R профита,
         остается 40% чистый Moonbag-ранер для ловли ракет +5%..+15%!
      4. Широкий Chandelier ATR-трейлинг (2.5 * ATR14, минимум 1.3%) активируется только от +2.2R,
         позволяя ракете пережить нормальные 5m откаты и собрать все трендовое движение!
      5. Time-Stop (35 минут): если пробой оказался ложным и за 35 минут цена не ушла даже на +0.45R,
         сделка закрывается без ожидания полного стоп-лосса, освобождая капитал.
    """
    def __init__(self):
        self.is_running = False
        self._last_log_time = 0.0
        self._last_shadow_check = 0.0

    async def _check_shadow_outcomes(self):
        """Проверяет свечи и экстремумы (High/Low) для теневого трекера отклонённых сетапов."""
        try:
            shadow_syms = list({t["symbol"] for t in portfolio.shadow_trades[:20] if "symbol" in t})
            if not shadow_syms:
                return
            shadow_data = {}
            for sym in shadow_syms:
                hl = await binance_client.fetch_recent_high_low(sym, limit=60)
                if hl:
                    cur, max_h, min_l = hl
                    shadow_data[sym] = {"current": cur, "high": max_h, "low": min_l}
                else:
                    p = await binance_client.fetch_price(sym)
                    if p and p > 0:
                        shadow_data[sym] = {"current": p, "high": p, "low": p}
            if shadow_data:
                portfolio.update_shadow_outcomes(shadow_data)
        except Exception:
            pass

    async def run_loop(self):
        self.is_running = True
        print("🛡️ [ExitManager] Асимметричный трендовый движок выхода активен (30%/30%/40% ATR Runner + 35m Time-Stop).", flush=True)
        while self.is_running:
            try:
                now = time.time()
                if (now - self._last_shadow_check) >= 45.0 and portfolio.shadow_trades:
                    self._last_shadow_check = now
                    await self._check_shadow_outcomes()

                positions = portfolio.open_positions
                if not positions:
                    await asyncio.sleep(2.0)
                    continue

                symbols = list(positions.keys())
                price_map = {}
                for sym in symbols:
                    p = await binance_client.fetch_price(sym)
                    if p and p > 0:
                        price_map[sym] = p

                if price_map:
                    portfolio.update_position_prices(price_map)

                now = time.time()
                should_log = (now - self._last_log_time) >= 15.0
                if should_log:
                    self._last_log_time = now

                tp1_part = float(getattr(config, "TP1_PARTIAL_PCT", 0.30))
                tp2_part_rem = float(getattr(config, "TP2_PARTIAL_OF_REMAINING", 0.4286))
                atr_mult = float(getattr(config, "RUNNER_ATR_MULT", 2.5))
                act_r = float(getattr(config, "RUNNER_ACTIVATION_R", 2.2))
                min_trail = float(getattr(config, "TRAILING_STOP_PCT", 0.013))
                time_stop_sec = int(getattr(config, "TIME_STOP_MINUTES", 35)) * 60

                for sym in symbols:
                    if sym not in portfolio.open_positions:
                        continue
                    pos = portfolio.open_positions[sym]
                    cur_price = pos.get("current_price", pos["entry_price"])
                    entry = pos["entry_price"]
                    wick_sl = pos["wick_sl"]
                    tp1 = pos["tp1"]
                    tp2 = pos["tp2"]
                    side = pos.get("side", "LONG")
                    atr_pct = float(pos.get("atr_pct", 0.006))
                    risk_dist = max(float(pos.get("risk_dist", abs(entry - pos.get("original_sl", wick_sl)))), entry * 0.005)
                    elapsed_sec = now - float(pos.get("opened_at", now))

                    if should_log:
                        print(
                            f"📊 [RUNNER TRACKER] {sym} ({side} {pos['leverage']}x): ${cur_price:.4f} (Вход: ${entry:.4f}) | "
                            f"PnL остатка: {pos['pnl_pct']:+.2f}% (${pos['unrealized_pnl']:+.2f}) | "
                            f"SL: ${wick_sl:.4f} | TP1: ${tp1:.4f} | TP2: ${tp2:.4f}",
                            flush=True
                        )

                    # ==========================================================
                    # ЛОГИКА СОПРОВОЖДЕНИЯ ДЛЯ LONG
                    # ==========================================================
                    if side == "LONG":
                        # 1. СТОП-ЛОСС / БЕЗУБЫТОК / CHANDELIER ATR TRAIL
                        if cur_price <= wick_sl:
                            if pos.get("tp2_hit"):
                                reason_label = f"🚀 ATR Runner Trail ({pos['pnl_pct']:+.1f}%)"
                            elif pos.get("breakeven_set"):
                                reason_label = f"🛡️ Breakeven / Profit Lock ({pos['pnl_pct']:+.1f}%)"
                            else:
                                reason_label = f"🛑 Structural Stop ({pos['pnl_pct']:+.1f}%)"
                            portfolio.close_position(sym, cur_price, reason=reason_label, partial_pct=1.0)
                            continue

                        # 2. TP1 (+1.5R): Фиксация 30% + Безубыток +0.20% на 70% ранера
                        if not pos["tp1_hit"] and cur_price >= tp1:
                            pos["tp1_hit"] = True
                            pos["wick_sl"] = round(max(pos["wick_sl"], entry * 1.0020), 6)
                            pos["breakeven_set"] = True
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP1 1.5R (+{pos['pnl_pct']:.1f}%): 30% в кэш",
                                partial_pct=tp1_part
                            )
                            continue

                        # 3. TP2 (+3.0R): Фиксация еще 30% от исходной позиции (остается 40% ранер!)
                        if pos["tp1_hit"] and not pos["tp2_hit"] and cur_price >= tp2:
                            pos["tp2_hit"] = True
                            pos["wick_sl"] = round(max(pos["wick_sl"], entry + 1.2 * risk_dist), 6)
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP2 3.0R (+{pos['pnl_pct']:.1f}%): еще 30% в кэш",
                                partial_pct=tp2_part_rem
                            )
                            continue

                        # 4. CHANDELIER ATR TRAILING (включается после +2.2R или TP2, чтобы не душить ракету сразу после TP1)
                        highest = pos.get("highest_price", cur_price)
                        if pos["tp1_hit"] and (pos["tp2_hit"] or highest >= entry + act_r * risk_dist):
                            trail_dist = max(atr_pct * atr_mult, min_trail)
                            trailing_sl_price = round(highest * (1.0 - trail_dist), 6)
                            if trailing_sl_price > pos["wick_sl"]:
                                pos["wick_sl"] = trailing_sl_price
                                portfolio.save()

                        # 5. TIME-STOP (35 мин без пробоя): выход из затухшей сделки
                        if not pos["tp1_hit"] and elapsed_sec >= time_stop_sec:
                            cur_r = (cur_price - entry) / risk_dist
                            if cur_r < 0.45:
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"⏱️ Time-Stop ({int(elapsed_sec//60)}м без импульса)",
                                    partial_pct=1.0
                                )
                                continue

                    # ==========================================================
                    # ЛОГИКА СОПРОВОЖДЕНИЯ ДЛЯ SHORT
                    # ==========================================================
                    else:
                        # 1. СТОП-ЛОСС / БЕЗУБЫТОК / CHANDELIER ATR TRAIL
                        if cur_price >= wick_sl:
                            if pos.get("tp2_hit"):
                                reason_label = f"🚀 ATR Runner Trail ({pos['pnl_pct']:+.1f}%)"
                            elif pos.get("breakeven_set"):
                                reason_label = f"🛡️ Breakeven / Profit Lock ({pos['pnl_pct']:+.1f}%)"
                            else:
                                reason_label = f"🛑 Structural Stop ({pos['pnl_pct']:+.1f}%)"
                            portfolio.close_position(sym, cur_price, reason=reason_label, partial_pct=1.0)
                            continue

                        # 2. TP1 (+1.5R): Фиксация 30% + Безубыток -0.20% на 70% ранера
                        if not pos["tp1_hit"] and cur_price <= tp1:
                            pos["tp1_hit"] = True
                            pos["wick_sl"] = round(min(pos["wick_sl"], entry * 0.9980), 6)
                            pos["breakeven_set"] = True
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP1 1.5R (+{pos['pnl_pct']:.1f}%): 30% в кэш",
                                partial_pct=tp1_part
                            )
                            continue

                        # 3. TP2 (+3.0R): Фиксация еще 30% от исходной позиции (остается 40% ранер!)
                        if pos["tp1_hit"] and not pos["tp2_hit"] and cur_price <= tp2:
                            pos["tp2_hit"] = True
                            pos["wick_sl"] = round(min(pos["wick_sl"], entry - 1.2 * risk_dist), 6)
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP2 3.0R (+{pos['pnl_pct']:.1f}%): еще 30% в кэш",
                                partial_pct=tp2_part_rem
                            )
                            continue

                        # 4. CHANDELIER ATR TRAILING ДЛЯ ШОРТА
                        lowest = pos.get("lowest_price", cur_price)
                        if pos["tp1_hit"] and (pos["tp2_hit"] or lowest <= entry - act_r * risk_dist):
                            trail_dist = max(atr_pct * atr_mult, min_trail)
                            trailing_sl_price = round(lowest * (1.0 + trail_dist), 6)
                            if trailing_sl_price < pos["wick_sl"]:
                                pos["wick_sl"] = trailing_sl_price
                                portfolio.save()

                        # 5. TIME-STOP (35 мин без пролива): выход из зависшего шорта
                        if not pos["tp1_hit"] and elapsed_sec >= time_stop_sec:
                            cur_r = (entry - cur_price) / risk_dist
                            if cur_r < 0.45:
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"⏱️ Time-Stop ({int(elapsed_sec//60)}м без импульса)",
                                    partial_pct=1.0
                                )
                                continue

                await asyncio.sleep(2.0)
            except Exception as e:
                print(f"⚠️ Ошибка в ExitManager: {e}", flush=True)
                await asyncio.sleep(2.0)

exit_manager = ExitManager()
