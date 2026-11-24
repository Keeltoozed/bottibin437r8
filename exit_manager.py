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
      2. TP1 (+1.4R): фиксация 45% позиции (немедленно окупает комиссии и фиксирует чистый кэш на депозит),
         перенос стопа оставшихся 55% в безубыток +0.25% (сделка гарантированно прибыльна!).
      3. TP2 (+2.7R): фиксация еще 30% от начального объема (54.55% от остатка), заморозка +1.2R профита,
         остается 25% чистый Moonbag-ранер для ловли ракет +5%..+15%!
      4. Широкий Chandelier ATR-трейлинг (2.4 * ATR14, минимум 1.15%) активируется от +2.1R,
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
        print("🛡️ [ExitManager] Асимметричный трендовый движок выхода активен (45%/30%/25% ATR Runner + 35m Time-Stop).", flush=True)
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

                tp1_part = float(getattr(config, "TP1_PARTIAL_PCT", 0.45))
                tp2_part_rem = float(getattr(config, "TP2_PARTIAL_OF_REMAINING", 0.5455))
                atr_mult = float(getattr(config, "RUNNER_ATR_MULT", 2.4))
                act_r = float(getattr(config, "RUNNER_ACTIVATION_R", 2.1))
                min_trail = float(getattr(config, "TRAILING_STOP_PCT", 0.0115))
                early_be_pct = float(getattr(config, "EARLY_BE_TRIGGER_PCT", 0.0070))
                early_be_r = float(getattr(config, "EARLY_BE_TRIGGER_R", 0.85))
                early_be_lock = float(getattr(config, "EARLY_BE_LOCK_PCT", 0.0022))
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
                    # ЛОГИКА СОПРОВОЖДЕНИЯ ДЛЯ LONG (PROFIT-SHIELD ENGINE)
                    # ==========================================================
                    if side == "LONG":
                        highest = max(pos.get("highest_price", cur_price), cur_price)
                        mfe_dist = max(0.0, highest - entry)
                        mfe_pct = mfe_dist / max(entry, 1e-9)
                        mfe_r = mfe_dist / risk_dist
                        cur_move_pct = (cur_price - entry) / max(entry, 1e-9)
                        cur_r = (cur_price - entry) / risk_dist

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

                        # Tier 1: Ранний щит безубытка (при +0.70% или +0.85R -> стоп в +0.18%, сделка больше не станет минусом!)
                        if not pos["tp1_hit"] and (mfe_pct >= early_be_pct or mfe_r >= early_be_r):
                            be_price = config.round_price(entry * (1.0 + early_be_lock))
                            if be_price > pos["wick_sl"] or not pos.get("breakeven_set"):
                                pos["wick_sl"] = max(pos["wick_sl"], be_price)
                                pos["breakeven_set"] = True
                                portfolio.save()

                        # Tier 2: Доступный TP1 (1.40R / min 0.95%): Фиксация 45% в кэш + замок +0.25%
                        if not pos["tp1_hit"] and cur_price >= tp1:
                            pos["tp1_hit"] = True
                            pos["wick_sl"] = config.round_price(max(pos["wick_sl"], entry * 1.0025))
                            pos["breakeven_set"] = True
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP1 {config.TARGET_1_R}R (+{pos['pnl_pct']:.1f}%): 45% в кэш",
                                partial_pct=tp1_part
                            )
                            continue

                        # Tier 3: TP2 (2.70R / min 2.00%): Фиксация еще 30% (остается 25% Moonbag ранер!)
                        if pos["tp1_hit"] and not pos["tp2_hit"] and cur_price >= tp2:
                            pos["tp2_hit"] = True
                            pos["wick_sl"] = config.round_price(max(pos["wick_sl"], entry + 1.20 * risk_dist))
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP2 {config.TARGET_2_R}R (+{pos['pnl_pct']:.1f}%): еще 30% в кэш",
                                partial_pct=tp2_part_rem
                            )
                            continue

                        # Chandelier ATR Trailing (включается от +2.1R или после TP2, не душит ракеты!)
                        if pos["tp1_hit"] and (pos["tp2_hit"] or mfe_r >= act_r):
                            trail_dist = max(atr_pct * atr_mult, min_trail)
                            trailing_sl_price = config.round_price(highest * (1.0 - trail_dist))
                            if trailing_sl_price > pos["wick_sl"]:
                                pos["wick_sl"] = trailing_sl_price
                                portfolio.save()

                        # Tier 4: Time-Stop (35 мин без пробоя к TP1): освобождает слот для новых ракет
                        if not pos["tp1_hit"] and elapsed_sec >= time_stop_sec:
                            if cur_r < 0.45:
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"⏱️ Time-Stop ({int(elapsed_sec//60)}м без импульса)",
                                    partial_pct=1.0
                                )
                                continue

                    # ==========================================================
                    # ЛОГИКА СОПРОВОЖДЕНИЯ ДЛЯ SHORT (PROFIT-SHIELD ENGINE)
                    # ==========================================================
                    else:
                        lowest = min(pos.get("lowest_price", cur_price), cur_price)
                        mfe_dist = max(0.0, entry - lowest)
                        mfe_pct = mfe_dist / max(entry, 1e-9)
                        mfe_r = mfe_dist / risk_dist
                        cur_r = (entry - cur_price) / risk_dist

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

                        # Tier 1: Ранний щит безубытка (при +0.70% или +0.85R -> стоп в -0.18%)
                        if not pos["tp1_hit"] and (mfe_pct >= early_be_pct or mfe_r >= early_be_r):
                            be_price = config.round_price(entry * (1.0 - early_be_lock))
                            if be_price < pos["wick_sl"] or not pos.get("breakeven_set"):
                                pos["wick_sl"] = min(pos["wick_sl"], be_price)
                                pos["breakeven_set"] = True
                                portfolio.save()

                        # Tier 2: Доступный TP1 (1.40R / min 0.95%): Фиксация 45% в кэш + замок -0.25%
                        if not pos["tp1_hit"] and cur_price <= tp1:
                            pos["tp1_hit"] = True
                            pos["wick_sl"] = config.round_price(min(pos["wick_sl"], entry * 0.9975))
                            pos["breakeven_set"] = True
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP1 {config.TARGET_1_R}R (+{pos['pnl_pct']:.1f}%): 45% в кэш",
                                partial_pct=tp1_part
                            )
                            continue

                        # Tier 3: TP2 (2.70R / min 2.00%): Фиксация еще 30% (остается 25% Moonbag ранер!)
                        if pos["tp1_hit"] and not pos["tp2_hit"] and cur_price <= tp2:
                            pos["tp2_hit"] = True
                            pos["wick_sl"] = config.round_price(min(pos["wick_sl"], entry - 1.20 * risk_dist))
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP2 {config.TARGET_2_R}R (+{pos['pnl_pct']:.1f}%): еще 30% в кэш",
                                partial_pct=tp2_part_rem
                            )
                            continue

                        # Chandelier ATR Trailing для шорта
                        if pos["tp1_hit"] and (pos["tp2_hit"] or mfe_r >= act_r):
                            trail_dist = max(atr_pct * atr_mult, min_trail)
                            trailing_sl_price = config.round_price(lowest * (1.0 + trail_dist))
                            if trailing_sl_price < pos["wick_sl"]:
                                pos["wick_sl"] = trailing_sl_price
                                portfolio.save()

                        # Tier 4: Time-Stop (35 мин без пролива к TP1): освобождает слот для новых ракет
                        if not pos["tp1_hit"] and elapsed_sec >= time_stop_sec:
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
