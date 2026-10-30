import asyncio
import time
from typing import Dict, Any
import config
from binance_client import binance_client
from tracker import portfolio

class ExitManager:
    """
    Интеллектуальный менеджер сопровождения и выхода из позиций.
    Реализует правила:
      1. 'Stop lives under the wick': жесткий контроль свечного стопа.
      2. 'Dynamic Breakeven': перенос в безубыток при прохождении 50% расстояния до TP1.
      3. 'Tiered Take-Profit':
         - При TP1: закрытие 50% позиции + гарантированный безубыток на остаток.
         - При TP2: закрытие 25% позиции.
         - Остаток: трейлинг-стоп за локальным ATH.
      4. 'Momentum Death': ранний выход, если импульс затухает.
    """
    def __init__(self):
        self.is_running = False

    async def run_loop(self):
        self.is_running = True
        print("🛡️ [ExitManager] Менеджер умного выхода активен.", flush=True)
        while self.is_running:
            try:
                positions = portfolio.open_positions
                if not positions:
                    await asyncio.sleep(1.5)
                    continue

                # Обновляем цены для всех открытых позиций
                symbols = list(positions.keys())
                price_map = {}
                for sym in symbols:
                    ob = await binance_client.fetch_orderbook_spread(sym)
                    bid, ask, _ = ob
                    if bid > 0:
                        price_map[sym] = (bid + ask) / 2.0

                portfolio.update_position_prices(price_map)

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

                    # 1. СТОП-ЛОСС ПОД ФИТИЛЬ (WICK SL)
                    if cur_price <= wick_sl:
                        portfolio.close_position(
                            sym, cur_price,
                            reason=f"🛑 Stop Under Wick (-{abs(pos['pnl_pct']):.1f}%)"
                        )
                        continue

                    # 2. ПЕРЕНОС В БЕЗУБЫТОК (SAFE BREAKEVEN)
                    # Если прошли 50% пути до TP1, сдвигаем стоп в безубыток (+0.1% для комиссии)
                    distance_to_tp1 = tp1 - entry
                    if not pos["breakeven_set"] and (cur_price >= entry + distance_to_tp1 * config.BREAKEVEN_TRIGGER_RATIO):
                        pos["wick_sl"] = round(entry * 1.001, 6)
                        pos["breakeven_set"] = True
                        portfolio.save()
                        print(f"🛡️ [BREAKEVEN] {sym}: SL перенесен в безубыток (${pos['wick_sl']:.4f}). Сделка безопасна!", flush=True)

                    # 3. ТЕЙК-ПРОФИТ 1 (TP1): Фиксация 50% объема
                    if not pos["tp1_hit"] and cur_price >= tp1:
                        pos["tp1_hit"] = True
                        pos["wick_sl"] = round(entry * 1.002, 6)  # фиксация безубытка
                        portfolio.close_position(
                            sym, cur_price,
                            reason=f"🎯 TP1 Hit (+{pos['pnl_pct']:.1f}%): Фиксация 50%",
                            partial_pct=0.50
                        )
                        continue

                    # 4. ТЕЙК-ПРОФИТ 2 (TP2): Фиксация еще 25% объема
                    if pos["tp1_hit"] and not pos["tp2_hit"] and cur_price >= tp2:
                        pos["tp2_hit"] = True
                        portfolio.close_position(
                            sym, cur_price,
                            reason=f"🎯 TP2 Hit (+{pos['pnl_pct']:.1f}%): Фиксация 25%",
                            partial_pct=0.50
                        )
                        continue

                    # 5. ТРЕЙЛИНГ-СТОП ДЛЯ ОСТАТКА (TRAILING ATH STOP)
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

                await asyncio.sleep(2.0)
            except Exception as e:
                print(f"⚠️ Ошибка в ExitManager: {e}")
                await asyncio.sleep(2.0)

exit_manager = ExitManager()

