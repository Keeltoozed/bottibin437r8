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

    @staticmethod
    def _compute_big_runner_trail(side: str, extreme_price: float, entry: float, risk_dist: float, atr_pct: float, mfe_r: float, current_sl: float, trail_start_r: float = 3.1) -> float:
        """Широкий Big-Runner ATR-трейлинг: активируется от trail_start_r (2.5R на 15m SM / 3.1R на 5m), не душит ракеты до +300%..+700%+."""
        if mfe_r >= 6.6:
            band = max(1.60 * atr_pct * extreme_price, 0.80 * risk_dist)
        elif mfe_r >= 4.5:
            band = max(1.85 * atr_pct * extreme_price, 1.00 * risk_dist)
        elif mfe_r >= trail_start_r:
            band = max(2.05 * atr_pct * extreme_price, 1.18 * risk_dist)
        else:
            return current_sl

        if side == "LONG":
            floor_p = entry + 1.15 * risk_dist if mfe_r >= trail_start_r else current_sl
            return max(floor_p, extreme_price - band)
        floor_p = entry - 1.15 * risk_dist if mfe_r >= trail_start_r else current_sl
        return min(floor_p, extreme_price + band)

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
        print(f"🛡️ [ExitManager] 6H MTF Rocket Hunter активен (TP1 {config.TARGET_1_R}R, TP1_PARTIAL {int(config.TP1_PARTIAL_PCT*100)}%, Time-Stop {config.TIME_STOP_MINUTES}м).", flush=True)
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
                    # Честная проверка порога Cross-Margin ликвидации аккаунта (0.5% Maintenance Margin от суммарного номинала):
                    tot_notional = sum(float(p.get("margin_usdt", 0.0)) * float(p.get("leverage", 1)) for p in portfolio.open_positions.values())
                    cur_eq_chk = portfolio.get_portfolio_summary()["equity"]
                    if tot_notional > 0 and cur_eq_chk <= tot_notional * 0.005:
                        print(f"💥 [CROSS LIQUIDATION] Equity (${cur_eq_chk:.2f}) упал ниже поддерживающей маржи (${tot_notional*0.005:.2f})!", flush=True)
                        for l_sym, l_pos in list(portfolio.open_positions.items()):
                            portfolio.close_position(l_sym, l_pos.get("current_price", l_pos["entry_price"]), reason="💥 Cross-Margin Liquidation", partial_pct=1.0)
                        continue

                now = time.time()
                should_log = (now - self._last_log_time) >= 15.0
                if should_log:
                    self._last_log_time = now

                tp1_part = float(getattr(config, "TP1_PARTIAL_PCT", 0.60))
                post_tp1_lock_r = float(getattr(config, "POST_TP1_LOCK_R", 0.35))
                early_be_pct = float(getattr(config, "EARLY_BE_TRIGGER_PCT", 9.99))
                early_be_r = float(getattr(config, "EARLY_BE_TRIGGER_R", 99.0))
                early_be_lock = float(getattr(config, "EARLY_BE_LOCK_PCT", 0.0022))
                time_stop_sec = int(getattr(config, "TIME_STOP_MINUTES", 0)) * 60
                ttl_sec = int(getattr(config, "TTL_HOURS", 24)) * 3600

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

                    # Индивидуальный динамический профиль выхода конкретно под эту сделку
                    ep = pos.get("exit_plan") or {}
                    tp1_r_val = float(ep.get("tp1_r", getattr(config, "TARGET_1_R", 1.72)))
                    tp1_share = float(ep.get("tp1_share", tp1_part))
                    tp1_lock = float(ep.get("tp1_lock_r", post_tp1_lock_r))
                    tp2_r_val = float(ep.get("tp2_r", 1.65))
                    tp2_share = float(ep.get("tp2_share", 0.0))
                    tp2_lock = float(ep.get("tp2_lock_r", 0.95))
                    trail_r_val = float(ep.get("trail_r", 2.50))

                    if should_log:
                        print(
                            f"📊 [RUNNER TRACKER] {sym} ({side} {pos['leverage']}x | {ep.get('profile', 'STD')}): {config.round_price(cur_price)} (Вход: {config.round_price(entry)}) | "
                            f"PnL: {pos['pnl_pct']:+.2f}% (${pos['unrealized_pnl']:+.2f}) | "
                            f"SL: {config.round_price(wick_sl)} | TP1: {config.round_price(tp1)} | TP2: {config.round_price(tp2)}",
                            flush=True
                        )

                    # ==========================================================
                    # ЛОГИКА СОПРОВОЖДЕНИЯ ДЛЯ LONG (ДИНАМИЧЕСКИЙ 3-STAGE ВЫХОД)
                    # ==========================================================
                    if side == "LONG":
                        highest = max(pos.get("highest_price", cur_price), cur_price)
                        mfe_dist = max(0.0, highest - entry)
                        mfe_pct = mfe_dist / max(entry, 1e-9)
                        mfe_r = mfe_dist / risk_dist
                        cur_r = (cur_price - entry) / risk_dist

                        # 1. СТОП-ЛОСС / БЕЗРИСКОВЫЙ ЗАМОК / ШИРОКИЙ BIG-RUNNER ТРЕЙЛ
                        if cur_price <= wick_sl:
                            if pos.get("tp1_hit") and mfe_r >= trail_r_val:
                                reason_label = f"🚀 Big-Runner Rocket Trail ({pos['pnl_pct']:+.1f}%)"
                            elif pos.get("breakeven_set"):
                                reason_label = f"🛡️ Profit-Lock Shield ({pos['pnl_pct']:+.1f}%)"
                            else:
                                reason_label = f"🛑 Structural Stop ({pos['pnl_pct']:+.1f}%)"
                            portfolio.close_position(sym, cur_price, reason=reason_label, partial_pct=1.0)
                            continue

                        if not pos["tp1_hit"] and early_be_r < 90.0 and (mfe_pct >= early_be_pct or mfe_r >= early_be_r):
                            be_price = config.round_price(entry * (1.0 + early_be_lock))
                            if be_price > pos["wick_sl"]:
                                pos["wick_sl"] = be_price
                                pos["breakeven_set"] = True
                                portfolio.save()

                        # Stage 1 (TP1 / Lock1): перенос SL в плюс (100% безрисковая в Full-Hold или фиксация доли в Partial)
                        if not pos["tp1_hit"] and cur_price >= tp1:
                            pos["tp1_hit"] = True
                            pos["wick_sl"] = config.round_price(max(pos["wick_sl"], entry + tp1_lock * risk_dist))
                            pos["breakeven_set"] = True
                            if tp1_share > 0.001:
                                part_label = int(round(tp1_share * 100))
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"🎯 TP1 {tp1_r_val:.2f}R (+{pos['pnl_pct']:.1f}%): {part_label}% в кэш",
                                    partial_pct=tp1_share
                                )
                                continue
                            pos.setdefault("partial_notes", []).append("Lock1(БУ+)")
                            portfolio.save()
                            print(f"🛡️ [STEP-LOCK 1] {sym}: пробит {tp1_r_val:.2f}R ({pos['pnl_pct']:+.1f}%) | 100% объема в ракете, SL в плюс {pos['wick_sl']}!", flush=True)

                        # Stage 2 (TP2 / Lock2): вторая ступень замка профита (+1.1R..+1.55R) на все 100% (или добор кэша в Partial)
                        if pos["tp1_hit"] and not pos.get("tp2_hit", False) and cur_price >= tp2:
                            pos["tp2_hit"] = True
                            pos["wick_sl"] = config.round_price(max(pos["wick_sl"], entry + tp2_lock * risk_dist))
                            if tp2_share > 0.001:
                                rem_frac = min(0.95, tp2_share / max(1.0 - tp1_share, 0.05))
                                tp2_label = int(round(tp2_share * 100))
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"🚀 TP2 {tp2_r_val:.2f}R (+{pos['pnl_pct']:.1f}%): еще {tp2_label}% в кэш",
                                    partial_pct=rem_frac
                                )
                                continue
                            pos.setdefault("partial_notes", []).append("Lock2(Профит)")
                            portfolio.save()
                            print(f"🔒 [STEP-LOCK 2] {sym}: пробит {tp2_r_val:.2f}R ({pos['pnl_pct']:+.1f}%) | 100% объема в ракете, SL поднят до {pos['wick_sl']}!", flush=True)

                        # Stage 3 (Trail): Широкий Big-Runner Ratchet (включается только от +3.1R!)
                        if pos["tp1_hit"]:
                            trail_sl = self._compute_big_runner_trail("LONG", highest, entry, risk_dist, atr_pct, mfe_r, pos["wick_sl"], trail_start_r=trail_r_val)
                            trailing_sl_price = config.round_price(trail_sl)
                            if trailing_sl_price > pos["wick_sl"]:
                                pos["wick_sl"] = trailing_sl_price
                                portfolio.save()

                        if time_stop_sec > 0 and not pos["tp1_hit"] and elapsed_sec >= time_stop_sec:
                            if cur_r < 0.45:
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"⏱️ Time-Stop ({int(elapsed_sec//60)}м без импульса)",
                                    partial_pct=1.0
                                )
                                continue

                        # Жесткий TTL (по умолчанию 24ч): закрывает зависшую без TP1 сделку и освобождает слот для свежей ракеты!
                        if ttl_sec > 0 and not pos["tp1_hit"] and elapsed_sec >= ttl_sec:
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"⏱️ TTL {int(ttl_sec//3600)}ч (высвобождение слота)",
                                partial_pct=1.0
                            )
                            continue

                    # ==========================================================
                    # ЛОГИКА СОПРОВОЖДЕНИЯ ДЛЯ SHORT (ДИНАМИЧЕСКИЙ 3-STAGE ВЫХОД)
                    # ==========================================================
                    else:
                        lowest = min(pos.get("lowest_price", cur_price), cur_price)
                        mfe_dist = max(0.0, entry - lowest)
                        mfe_pct = mfe_dist / max(entry, 1e-9)
                        mfe_r = mfe_dist / risk_dist
                        cur_r = (entry - cur_price) / risk_dist

                        # 1. СТОП-ЛОСС / БЕЗРИСКОВЫЙ ЗАМОК / ШИРОКИЙ BIG-RUNNER ТРЕЙЛ
                        if cur_price >= wick_sl:
                            if pos.get("tp1_hit") and mfe_r >= trail_r_val:
                                reason_label = f"🚀 Big-Runner Dump Trail ({pos['pnl_pct']:+.1f}%)"
                            elif pos.get("breakeven_set"):
                                reason_label = f"🛡️ Profit-Lock Shield ({pos['pnl_pct']:+.1f}%)"
                            else:
                                reason_label = f"🛑 Structural Stop ({pos['pnl_pct']:+.1f}%)"
                            portfolio.close_position(sym, cur_price, reason=reason_label, partial_pct=1.0)
                            continue

                        if not pos["tp1_hit"] and early_be_r < 90.0 and (mfe_pct >= early_be_pct or mfe_r >= early_be_r):
                            be_price = config.round_price(entry * (1.0 - early_be_lock))
                            if be_price < pos["wick_sl"]:
                                pos["wick_sl"] = be_price
                                pos["breakeven_set"] = True
                                portfolio.save()

                        # Stage 1 (TP1 / Lock1): перенос SL в плюс (100% безрисковая в Full-Hold или фиксация доли в Partial)
                        if not pos["tp1_hit"] and cur_price <= tp1:
                            pos["tp1_hit"] = True
                            pos["wick_sl"] = config.round_price(min(pos["wick_sl"], entry - tp1_lock * risk_dist))
                            pos["breakeven_set"] = True
                            if tp1_share > 0.001:
                                part_label = int(round(tp1_share * 100))
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"🎯 TP1 {tp1_r_val:.2f}R (+{pos['pnl_pct']:.1f}%): {part_label}% в кэш",
                                    partial_pct=tp1_share
                                )
                                continue
                            pos.setdefault("partial_notes", []).append("Lock1(БУ+)")
                            portfolio.save()
                            print(f"🛡️ [STEP-LOCK 1] {sym}: пробит {tp1_r_val:.2f}R ({pos['pnl_pct']:+.1f}%) | 100% объема в ракете, SL в плюс {pos['wick_sl']}!", flush=True)

                        # Stage 2 (TP2 / Lock2): вторая ступень замка профита на все 100% (или добор кэша в Partial)
                        if pos["tp1_hit"] and not pos.get("tp2_hit", False) and cur_price <= tp2:
                            pos["tp2_hit"] = True
                            pos["wick_sl"] = config.round_price(min(pos["wick_sl"], entry - tp2_lock * risk_dist))
                            if tp2_share > 0.001:
                                rem_frac = min(0.95, tp2_share / max(1.0 - tp1_share, 0.05))
                                tp2_label = int(round(tp2_share * 100))
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"🚀 TP2 {tp2_r_val:.2f}R (+{pos['pnl_pct']:.1f}%): еще {tp2_label}% в кэш",
                                    partial_pct=rem_frac
                                )
                                continue
                            pos.setdefault("partial_notes", []).append("Lock2(Профит)")
                            portfolio.save()
                            print(f"🔒 [STEP-LOCK 2] {sym}: пробит {tp2_r_val:.2f}R ({pos['pnl_pct']:+.1f}%) | 100% объема в ракете, SL поднят до {pos['wick_sl']}!", flush=True)

                        # Stage 3 (Trail): Широкий Big-Runner Ratchet для шорт-ранера (от +3.1R!)
                        if pos["tp1_hit"]:
                            trail_sl = self._compute_big_runner_trail("SHORT", lowest, entry, risk_dist, atr_pct, mfe_r, pos["wick_sl"], trail_start_r=trail_r_val)
                            trailing_sl_price = config.round_price(trail_sl)
                            if trailing_sl_price < pos["wick_sl"]:
                                pos["wick_sl"] = trailing_sl_price
                                portfolio.save()

                        if time_stop_sec > 0 and not pos["tp1_hit"] and elapsed_sec >= time_stop_sec:
                            if cur_r < 0.45:
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"⏱️ Time-Stop ({int(elapsed_sec//60)}м без импульса)",
                                    partial_pct=1.0
                                )
                                continue

                        if ttl_sec > 0 and not pos["tp1_hit"] and elapsed_sec >= ttl_sec:
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"⏱️ TTL {int(ttl_sec//3600)}ч (высвобождение слота)",
                                partial_pct=1.0
                            )
                            continue

                await asyncio.sleep(2.0)
            except Exception as e:
                print(f"⚠️ Ошибка в ExitManager: {e}", flush=True)
                await asyncio.sleep(2.0)

exit_manager = ExitManager()
