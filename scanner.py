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
    Высокоскоростной автономный сканер рынка Binance Futures.
    Параллельно (через Semaphore) анализирует пары, отсекает мусор через Hard Gates
    и передает кандидатов (LONG и SHORT) на вердикт в Groq AI Engine.
    """
    def __init__(self):
        self.is_running = False
        self.cooldowns: Dict[str, float] = {}

    async def scan_market_once(self) -> List[Dict[str, Any]]:
        """Один высокоскоростной параллельный проход сканирования рынка."""
        if portfolio.is_paused:
            return []

        now_str = time.strftime("%H:%M:%S")
        portfolio.last_scan_str = now_str

        # 1. UNIVERSE: Получаем топ волатильные пары Binance Futures
        tickers = await binance_client.fetch_top_tickers(
            min_vol_usdt=config.MIN_24H_VOLUME_USDT,
            limit=config.SCAN_TICKERS_LIMIT
        )
        portfolio.funnel_stats["universe"] += len(tickers)
        print(f"📡 [SCAN] {now_str} — Загружено {len(tickers)} пар Binance (Параллельный радар)...", flush=True)

        now = time.time()
        sem = asyncio.Semaphore(8)  # 8 одновременных запросов для мгновенной скорости

        async def check_ticker(t: Dict[str, Any]) -> Any:
            sym = t["symbol"]

            # Проверка кулдауна и открытых позиций
            if sym in self.cooldowns and (now - self.cooldowns[sym]) < (config.PAIR_COOLDOWN_MINUTES * 60):
                return None
            if sym in portfolio.open_positions:
                return None

            async with sem:
                # 2. HARD GATE: Спред в стакане
                _, _, spread = await binance_client.fetch_orderbook_spread(sym)
                if spread > config.MAX_SPREAD_PCT:
                    return None

                # 3. HARD GATE: Анализ свечей и объема
                analysis = await binance_client.fetch_candles_analysis(sym, interval="5m", limit=20)
                if not analysis:
                    return None

                surge = analysis["volume_surge_ratio"]
                pct_5m = analysis["pct_5m"]
                sl_dist = analysis["sl_pct_distance"]
                short_sl_dist = analysis.get("short_sl_dist", 0.05)

                min_impulse = getattr(config, "MIN_5M_PRICE_IMPULSE_PCT", 0.55)

                # Проверка условий LONG (импульсный памп с активным объемом)
                is_long = (
                    surge >= config.MIN_5M_VOLUME_SURGE_RATIO and
                    pct_5m >= min_impulse and
                    sl_dist <= config.MAX_ALLOWED_SL_PCT
                )

                # Проверка условий SHORT (пробойный дамп с давлением продавцов)
                is_short = (
                    config.ENABLE_SHORT and
                    surge >= config.MIN_5M_VOLUME_SURGE_RATIO and
                    pct_5m <= -min_impulse and
                    short_sl_dist <= config.MAX_ALLOWED_SL_PCT
                )

                if is_long:
                    self.cooldowns[sym] = now
                    print(f"🔥 [HARD GATE PASSED - LONG] {sym}: всплеск {surge}x, +{pct_5m:.2f}% (5m) ➔ Groq...", flush=True)
                    return {**t, **analysis, "candidate_side": "LONG"}
                elif is_short:
                    self.cooldowns[sym] = now
                    print(f"🔻 [HARD GATE PASSED - SHORT] {sym}: всплеск {surge}x, {pct_5m:.2f}% (5m) ➔ Groq...", flush=True)
                    return {**t, **analysis, "candidate_side": "SHORT"}
                return None

        tasks = [check_ticker(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates_passed_hard = [r for r in results if r and isinstance(r, dict)]

        portfolio.funnel_stats["hard_gates"] += len(candidates_passed_hard)

        # 4. GROQ SOFT GATE (JEV AI ENGINE)
        for ctx in candidates_passed_hard:
            sym = ctx["symbol"]
            cand_side = ctx.get("candidate_side", "LONG")
            portfolio.funnel_stats["groq_evaluated"] += 1

            approved, groq_eval = await groq_engine.evaluate_setup(ctx)

            default_sl = ctx["wick_stop_loss"] if cand_side == "LONG" else ctx.get("short_wick_sl", ctx["current_price"] * 1.01)
            default_tp1 = round(ctx["current_price"] * (1.02 if cand_side == "LONG" else 0.98), 4)

            eval_entry = {
                "symbol": sym,
                "side": cand_side,
                "price": ctx["current_price"],
                "decision": groq_eval.get("decision", "SKIP"),
                "confidence": groq_eval.get("confidence", 0.0),
                "reason": groq_eval.get("reason", ""),
                "sl": groq_eval.get("stop_loss", default_sl),
                "tp1": groq_eval.get("tp1", default_tp1),
                "surge": ctx["volume_surge_ratio"],
                "pullback": round(ctx.get("pullback_from_high_pct", 0) * 100, 2) if cand_side == "LONG" else round(ctx.get("bounce_from_low_pct", 0) * 100, 2),
                "time": time.strftime("%H:%M:%S")
            }
            portfolio.add_evaluation(eval_entry)
            print(f"🤖 [GROQ JEV] {sym} ({cand_side}): {eval_entry['decision']} ({int(eval_entry['confidence']*100)}%) | {eval_entry['reason']}", flush=True)

            if approved:
                portfolio.funnel_stats["passed"] += 1

                # 1. Проверка дневного лимита Circuit Breaker (trader-risk)
                if portfolio.get_daily_loss() >= config.MAX_DAILY_LOSS_USD:
                    print(f"🛑 [CIRCUIT BREAKER] Дневной лимит убытка (-${portfolio.get_daily_loss():.2f}) исчерпан. Защита депозита активна.", flush=True)
                    continue

                entry_p = ctx["current_price"]
                wick_sl = eval_entry["sl"]

                # Минимальное расстояние тейк-профитов для защиты от микро-сделок:
                # TP1: минимум 1.5% хода цены (+112.5% ROI при 75x)
                # TP2: минимум 3.0% хода цены (+225.0% ROI при 75x)
                min_tp1_dist = entry_p * config.TP1_PCT
                min_tp2_dist = entry_p * config.TP2_PCT

                if cand_side == "LONG":
                    risk_per_coin = max(entry_p - wick_sl, entry_p * 0.002)
                    tp1_2r = round(max(entry_p + (config.TARGET_1_R * risk_per_coin), entry_p + min_tp1_dist), 6)
                    tp2_3r = round(max(entry_p + (config.TARGET_2_R * risk_per_coin), entry_p + min_tp2_dist), 6)
                else:  # SHORT
                    risk_per_coin = max(wick_sl - entry_p, entry_p * 0.002)
                    tp1_2r = round(min(entry_p - (config.TARGET_1_R * risk_per_coin), entry_p - min_tp1_dist), 6)
                    tp2_3r = round(min(entry_p - (config.TARGET_2_R * risk_per_coin), entry_p - min_tp2_dist), 6)

                risk_pct = risk_per_coin / entry_p

                # 2. Оптимальный расчет маржи для ощутимой прибыли ($3.00 - $7.00+ на сделку):
                # На старте $20 используем рабочую маржу $6.00 (или 30-35% капитала при разгоне сложным процентом).
                # Ограничиваем не более 45% от доступного свободного кеша, чтобы всегда помещались 2 сделки.
                lev_to_use = getattr(portfolio, "current_leverage", config.LEVERAGE)
                target_margin = max(config.TRADE_AMOUNT_USDT, portfolio.cash * 0.35)
                actual_margin = round(min(target_margin, max(portfolio.cash * 0.45, 3.0)), 2)

                # Проверка лимитов портфеля и открытие позиции
                if len(portfolio.open_positions) < config.MAX_CONCURRENT_POSITIONS and portfolio.cash >= actual_margin:
                    portfolio.open_position(
                        symbol=sym,
                        side=cand_side,
                        entry_price=entry_p,
                        size_usdt=actual_margin,
                        wick_sl=wick_sl,
                        tp1=tp1_2r,
                        tp2=tp2_3r,
                        groq_reason=f"2R/3R Target | {eval_entry['reason']}",
                        leverage=lev_to_use
                    )
            else:
                # Сохраняем в Shadow Tracker для анализа отклонённых сетапов
                portfolio.shadow_trades.insert(0, {
                    "symbol": sym,
                    "side": cand_side,
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
        print(f"📡 [MarketScanner] Автономный сканер запущен (Интервал: {config.SCAN_INTERVAL_SECONDS}с, LONG+SHORT)...", flush=True)
        while self.is_running:
            try:
                await self.scan_market_once()
            except Exception as e:
                print(f"⚠️ Ошибка в MarketScanner: {e}", flush=True)
            await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)

market_scanner = MarketScanner()
