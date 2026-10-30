import asyncio
import time
from typing import Dict, Any
import config
from binance_client import binance_client
from tracker import portfolio

class ExitManager:
    """
    Интеллектуальный менеджер сопровождения и выхода из позиций (LONG и SHORT).
    Реализует правила Day-Trader Discipline:
      1. 'Stop lives under/above the wick': сделка свободно дышит в рамках исходного стоп-лосса.
         Никаких преждевременных микро-безубытков, удушающих сделку из-за рыночного шума!
      2. 'Tiered Take-Profit':
         - При TP1 (+1.5% хода цены = +112.5% ROI на 75x): закрытие 50% объема с фиксацией реальной прибыли в депозит.
         - Только ПОСЛЕ взятия TP1: стоп оставшейся части переносится в гарантированный безубыток с запасом на комиссию.
         - При TP2 (+3.0% хода цены = +225.0% ROI): фиксация еще 25% объема.
         - Остаток (25%): трейлинг-стоп для ловли мощных трендовых выносов.
      3. 'Live Price Tracking': непрерывный мониторинг рыночных цен каждые 2 секунды.
    """
    def __init__(self):
        self.is_running = False
        self._last_log_time = 0.0

    async def run_loop(self):
        self.is_running = True
        print("🛡️ [ExitManager] Менеджер умного выхода активен (LONG + SHORT).", flush=True)
        while self.is_running:
            try:
                positions = portfolio.open_positions
                if not positions:
                    await asyncio.sleep(2.0)
                    continue

                # Обновляем цены для всех открытых позиций
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

                # Проверяем каждую позицию на условия выхода
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

                    if should_log:
                        print(
                            f"📊 [PRICE TRACKER] {sym} ({side} {pos['leverage']}x): ${cur_price:.4f} (Вход: ${entry:.4f}) | "
                            f"PnL: {pos['pnl_pct']:+.2f}% (${pos['unrealized_pnl']:+.2f}) | "
                            f"SL: ${wick_sl:.4f} | TP1: ${tp1:.4f}",
                            flush=True
                        )

                    # ==========================================================
                    # ЛОГИКА ВЫХОДА ДЛЯ LONG
                    # ==========================================================
                    if side == "LONG":
                        # 1. СТОП-ЛОСС ПОД ФИТИЛЬ (ИЛИ БЕЗУБЫТОК ПОСЛЕ TP1)
                        if cur_price <= wick_sl:
                            reason_label = (
                                f"🛡️ Breakeven Exit ({pos['pnl_pct']:+.1f}%)"
                                if pos.get("breakeven_set")
                                else f"🛑 Stop Under Wick ({pos['pnl_pct']:+.1f}%)"
                            )
                            portfolio.close_position(
                                sym, cur_price,
                                reason=reason_label
                            )
                            continue

                        # 2. ТЕЙК-ПРОФИТ 1 (TP1): Фиксация 50% объема в плюс
                        if not pos["tp1_hit"] and cur_price >= tp1:
                            pos["tp1_hit"] = True
                            # После взятия крупного профита TP1 переносим стоп на остаток в гарантированный плюс (+0.2%)
                            pos["wick_sl"] = round(entry * 1.002, 6)
                            pos["breakeven_set"] = True
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP1 Hit (+{pos['pnl_pct']:.1f}%): Фиксация 50%",
                                partial_pct=0.50
                            )
                            print(f"🎯 [TP1 HIT] {sym} (LONG): Зафиксировано 50% прибыли! Стоп на остаток в плюсе (${pos['wick_sl']:.4f}).", flush=True)
                            continue

                        # 3. ТЕЙК-ПРОФИТ 2 (TP2): Фиксация еще 25% объема
                        if pos["tp1_hit"] and not pos["tp2_hit"] and cur_price >= tp2:
                            pos["tp2_hit"] = True
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP2 Hit (+{pos['pnl_pct']:.1f}%): Фиксация 25%",
                                partial_pct=0.50
                            )
                            print(f"🎯 [TP2 HIT] {sym} (LONG): Зафиксировано еще 25% на цели 3R!", flush=True)
                            continue

                        # 4. ТРЕЙЛИНГ-СТОП ДЛЯ ОСТАТКА (активен только после взятия TP1)
                        if pos["tp1_hit"]:
                            highest = pos.get("highest_price", cur_price)
                            trailing_sl_price = round(highest * (1.0 - config.TRAILING_STOP_PCT), 6)
                            if trailing_sl_price > pos["wick_sl"]:
                                pos["wick_sl"] = trailing_sl_price
                                portfolio.save()

                            if cur_price <= trailing_sl_price:
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"🚀 Trailing SL Triggered (+{pos['pnl_pct']:.1f}%)"
                                )
                                continue

                    # ==========================================================
                    # ЛОГИКА ВЫХОДА ДЛЯ SHORT
                    # ==========================================================
                    else:
                        # 1. СТОП-ЛОСС НАД ФИТИЛЕМ (ИЛИ БЕЗУБЫТОК ПОСЛЕ TP1)
                        if cur_price >= wick_sl:
                            reason_label = (
                                f"🛡️ Breakeven Exit ({pos['pnl_pct']:+.1f}%)"
                                if pos.get("breakeven_set")
                                else f"🛑 Stop Above Wick ({pos['pnl_pct']:+.1f}%)"
                            )
                            portfolio.close_position(
                                sym, cur_price,
                                reason=reason_label
                            )
                            continue

                        # 2. ТЕЙК-ПРОФИТ 1 (TP1): Фиксация 50% объема (цена упала до tp1)
                        if not pos["tp1_hit"] and cur_price <= tp1:
                            pos["tp1_hit"] = True
                            # После взятия крупного профита TP1 переносим стоп на остаток в гарантированный плюс (+0.2% ниже входа)
                            pos["wick_sl"] = round(entry * 0.998, 6)
                            pos["breakeven_set"] = True
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP1 Hit (+{pos['pnl_pct']:.1f}%): Фиксация 50%",
                                partial_pct=0.50
                            )
                            print(f"🎯 [TP1 HIT] {sym} (SHORT): Зафиксировано 50% прибыли! Стоп на остаток в плюсе (${pos['wick_sl']:.4f}).", flush=True)
                            continue

                        # 3. ТЕЙК-ПРОФИТ 2 (TP2): Фиксация еще 25% объема
                        if pos["tp1_hit"] and not pos["tp2_hit"] and cur_price <= tp2:
                            pos["tp2_hit"] = True
                            portfolio.close_position(
                                sym, cur_price,
                                reason=f"🎯 TP2 Hit (+{pos['pnl_pct']:.1f}%): Фиксация 25%",
                                partial_pct=0.50
                            )
                            print(f"🎯 [TP2 HIT] {sym} (SHORT): Зафиксировано еще 25% на цели 3R!", flush=True)
                            continue

                        # 4. ТРЕЙЛИНГ-СТОП ДЛЯ ШОРТА (следует сверху за локальным минимумом, активен после TP1)
                        if pos["tp1_hit"]:
                            lowest = pos.get("lowest_price", cur_price)
                            trailing_sl_price = round(lowest * (1.0 + config.TRAILING_STOP_PCT), 6)
                            if trailing_sl_price < pos["wick_sl"]:
                                pos["wick_sl"] = trailing_sl_price
                                portfolio.save()

                            if cur_price >= trailing_sl_price:
                                portfolio.close_position(
                                    sym, cur_price,
                                    reason=f"🚀 Trailing SL Triggered (+{pos['pnl_pct']:.1f}%)"
                                )
                                continue

                await asyncio.sleep(2.0)
            except Exception as e:
                print(f"⚠️ Ошибка в ExitManager: {e}", flush=True)
                await asyncio.sleep(2.0)

exit_manager = ExitManager()
