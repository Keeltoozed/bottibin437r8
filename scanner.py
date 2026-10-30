import sys
import os

# Гарантируем немедленный вывод логов на Render / Docker
os.environ["PYTHONUNBUFFERED"] = "1"
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

import asyncio
import time
from typing import Dict, Any, List
import config
from binance_client import binance_client
from groq_engine import groq_engine
from tracker import portfolio

class MarketScanner:
    """
    Автономный сканер рынка Binance Futures.
    Непрерывно анализирует топовые пары, отсекает мусор через Hard Gates
    и передает кандидатов на вердикт в Groq AI Engine.
    """
    def __init__(self):
        self.is_running = False
        self.cooldowns: Dict[str, float] = {}

    async def scan_market_once(self) -> List[Dict[str, Any]]:
        """Один проход сканирования рынка."""
        if portfolio.is_paused:
            return []

        now_str = time.strftime("%H:%M:%S")
        portfolio.last_scan_str = now_str

        # 1. UNIVERSE: Получаем топ пары Binance Futures
        tickers = await binance_client.fetch_top_tickers(
            min_vol_usdt=config.MIN_24H_VOLUME_USDT,
            limit=config.SCAN_TICKERS_LIMIT
        )
        portfolio.funnel_stats["universe"] += len(tickers)
        print(f"📡 [SCAN] {now_str} — Загружено {len(tickers)} пар Binance (Топ волатильные)...", flush=True)

        candidates_passed_hard = []
        now = time.time()

        for t in tickers:
            sym = t["symbol"]

            # Проверка кулдауна
            if sym in self.cooldowns and (now - self.cooldowns[sym]) < (config.PAIR_COOLDOWN_MINUTES * 60):
                continue
            if sym in portfolio.open_positions:
                continue

            # 2. HARD GATE: Спред в стакане
            _, _, spread = await binance_client.fetch_orderbook_spread(sym)
            if spread > config.MAX_SPREAD_PCT:
                continue

            # 3. HARD GATE: Анализ свечей и объема (всплеск объема + динамика)
            analysis = await binance_client.fetch_candles_analysis(sym, interval="5m", limit=20)
            if not analysis:
                continue

            surge = analysis["volume_surge_ratio"]
            pct_5m = analysis["pct_5m"]
            sl_dist = analysis["sl_pct_distance"]

            # Ищем памп / пробойный импульс (всплеск объема и положительный моментум)
            if surge >= config.MIN_5M_VOLUME_SURGE_RATIO and pct_5m >= 0.35 and sl_dist <= config.MAX_ALLOWED_SL_PCT:
                context = {**t, **analysis}
                candidates_passed_hard.append(context)
                self.cooldowns[sym] = now
                print(f"🔥 [HARD GATE PASSED] {sym}: всплеск {surge}x, +{pct_5m:.2f}% (5m) ➔ Отправляем в Groq...", flush=True)

        portfolio.funnel_stats["hard_gates"] += len(candidates_passed_hard)

        # 4. GROQ SOFT GATE (JEV AI ENGINE)
        for ctx in candidates_passed_hard:
            sym = ctx["symbol"]
            portfolio.funnel_stats["groq_evaluated"] += 1

            approved, groq_eval = await groq_engine.evaluate_setup(ctx)

            eval_entry = {
                "symbol": sym,
                "price": ctx["current_price"],
                "decision": groq_eval.get("decision", "SKIP"),
                "confidence": groq_eval.get("confidence", 0.0),
                "reason": groq_eval.get("reason", ""),
                "sl": groq_eval.get("stop_loss", ctx["wick_stop_loss"]),
                "tp1": groq_eval.get("tp1", round(ctx["current_price"] * 1.025, 4)),
                "surge": ctx["volume_surge_ratio"],
                "pullback": round(ctx.get("pullback_from_high_pct", 0) * 100, 2),
                "time": time.strftime("%H:%M:%S")
            }
            portfolio.add_evaluation(eval_entry)
            print(f"🤖 [GROQ JEV] {sym}: {eval_entry['decision']} ({int(eval_entry['confidence']*100)}%) | {eval_entry['reason']}", flush=True)

            if approved:
                portfolio.funnel_stats["passed"] += 1

                # Проверка лимитов портфеля ($20 банкролл)
                if len(portfolio.open_positions) < config.MAX_CONCURRENT_POSITIONS and portfolio.cash >= config.TRADE_AMOUNT_USDT:
                    portfolio.open_position(
                        symbol=sym,
                        side="LONG",
                        entry_price=ctx["current_price"],
                        size_usdt=config.TRADE_AMOUNT_USDT,
                        wick_sl=eval_entry["sl"],
                        tp1=eval_entry["tp1"],
                        tp2=groq_eval.get("tp2", round(ctx["current_price"] * 1.05, 4)),
                        groq_reason=eval_entry["reason"],
                        leverage=config.LEVERAGE
                    )
            else:
                # Сохраняем в Shadow Tracker для анализа упущенных / спасенных сетапов
                portfolio.shadow_trades.insert(0, {
                    "symbol": sym,
                    "rejected_at_price": ctx["current_price"],
                    "reason": eval_entry["reason"],
                    "time": time.strftime("%H:%M:%S"),
                    "score": eval_entry["confidence"]
                })
                if len(portfolio.shadow_trades) > 50:
                    portfolio.shadow_trades = portfolio.shadow_trades[:50]
                portfolio.save()

        return candidates_passed_hard

    async def run_loop(self):
        self.is_running = True
        print(f"📡 [MarketScanner] Автономный сканер запущен (Интервал: {config.SCAN_INTERVAL_SECONDS}с)...", flush=True)
        while self.is_running:
            try:
                await self.scan_market_once()
            except Exception as e:
                print(f"⚠️ Ошибка в MarketScanner: {e}", flush=True)
            await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)

market_scanner = MarketScanner()
