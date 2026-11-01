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
from obsidian_vault import obsidian_vault
from ml_engine import ml_engine
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
        self._last_log_time = 0.0

    async def scan_market_once(self) -> List[Dict[str, Any]]:
        """Один высокоскоростной параллельный проход сканирования рынка."""
        now = time.time()
        now_str = time.strftime("%H:%M:%S")
        portfolio.last_scan_str = now_str

        # Проверка ручной паузы и предохранителя Circuit Breaker
        pause_until = getattr(portfolio, "pause_until", 0.0)
        if portfolio.is_paused or now < pause_until:
            rem = int(pause_until - now)
            if rem > 0:
                portfolio.btc_regime_str = f"🛑 Пауза Circuit Breaker ({rem} сек)"
            return []

        # Предохранитель депозита: максимум 2 убытка в день (как в бектесте)
        if portfolio.is_daily_limit_reached():
            portfolio.btc_regime_str = f"🛑 Дневной лимит 2 убытка достигнут ({portfolio.daily_losses_count}/{config.DAILY_LOSS_LIMIT})"
            return []

        # Лимит одновременных позиций (строго 2 позиции)
        if len(portfolio.open_positions) >= config.MAX_CONCURRENT_POSITIONS:
            return []

        # 0. MACRO GUARD: Проверяем состояние Bitcoin (Поводырь рынка и защита от негативных новостей)
        btc_regime = await binance_client.fetch_btc_regime()
        portfolio.btc_regime_str = btc_regime.get("status_str", "")

        # 1. UNIVERSE: Получаем расширенный радар (Ракеты + Ликвидность)
        tickers = await binance_client.fetch_top_tickers(
            min_vol_usdt=config.MIN_24H_VOLUME_USDT,
            limit=config.SCAN_TICKERS_LIMIT
        )
        portfolio.funnel_stats["universe"] += len(tickers)

        # Выводим сводный лог радара раз в минуту, чтобы не забивать экран спамом
        should_log = (now - self._last_log_time) >= 60.0
        if should_log:
            self._last_log_time = now
            btc_p = btc_regime.get("pct_15m", 0.0)
            print(f"📡 [РАДАР] {now_str} — Мониторинг {len(tickers)} пар Binance (Selective A+ Day-Trader) | BTC: {btc_p:+.2f}% | Оценок Groq: {portfolio.funnel_stats['groq_evaluated']}", flush=True)

        # Предварительно загружаем стаканы всех пар за 1 сетевой вызов
        await binance_client.fetch_all_book_tickers()
        sem = asyncio.Semaphore(16)  # 16 параллельных потоков для высокой скорости

        async def check_ticker(t: Dict[str, Any]) -> Any:
            sym = t["symbol"]

            # Проверка белого и черного списков
            strict = getattr(config, "STRICT_WHITELIST_ONLY", True)
            if strict and sym not in getattr(config, "TOP_CRYPTO_UNIVERSE", []):
                return None
            if sym in getattr(config, "EXCLUDED_TICKERS", set()):
                return None

            # Проверка кулдауна, карантина и открытых позиций
            lock_until = portfolio.symbol_lockouts.get(sym, 0.0)
            if now < lock_until:
                return None
            elif sym in portfolio.symbol_lockouts:
                del portfolio.symbol_lockouts[sym]

            if sym in self.cooldowns and (now - self.cooldowns[sym]) < (config.PAIR_COOLDOWN_MINUTES * 60):
                portfolio.funnel_stats["cooldown_blocked"] = portfolio.funnel_stats.get("cooldown_blocked", 0) + 1
                return None
            if sym in portfolio.open_positions:
                return None

            async with sem:
                # 2. HARD GATE: Спред в стакане
                _, _, spread = await binance_client.fetch_orderbook_spread(sym)
                if spread > config.MAX_SPREAD_PCT:
                    portfolio.funnel_stats["gate_failed"] = portfolio.funnel_stats.get("gate_failed", 0) + 1
                    return None

                # 3. Получаем 5m свечной анализ (80 свечей для расчета EMA50, RSI14, ATR, фитилей)
                analysis = await binance_client.fetch_candles_analysis(sym, interval="5m", limit=80)
                if not analysis:
                    return None

                pct_5m = analysis.get("pct_5m", 0.0)
                surge = analysis.get("volume_surge_ratio", 1.0)
                upper_wick = analysis.get("upper_wick_pct", 0.0)
                lower_wick = analysis.get("lower_wick_pct", 0.0)
                sl_long_dist = analysis.get("sl_pct_distance", 0.01)
                sl_short_dist = analysis.get("short_sl_dist", 0.01)

                # ==============================================================
                # 4. СЕЛЕКТИВНЫЕ ПРАВИЛА ВХОДА A+ (100% ИЗ БЕКТЕСТА REALISTIC_BACKTEST_7D)
                # 1. Четкий взрыв объема >= 1.50x
                # 2. Амплитуда свечи >= 0.65%
                # 3. Фитиль защиты уровня >= 0.25 (отбой от покупателей / сопротивления)
                # 4. Нет истощения: противоположный встречный фитиль <= 0.30
                # 5. Стоп в пределах скальперского допуска (0.3% - 1.2%)
                # ==============================================================
                is_long = (
                    surge >= config.MIN_5M_VOLUME_SURGE_RATIO and
                    pct_5m >= config.MIN_5M_PRICE_IMPULSE_PCT and
                    lower_wick >= config.WICK_REJECTION_MIN and
                    upper_wick <= config.WICK_EXHAUSTION_MAX and
                    config.STOP_LOSS_MIN_PCT <= sl_long_dist <= config.STOP_LOSS_MAX_PCT and
                    not btc_regime.get("is_dumping", False)
                )

                is_short = (
                    surge >= config.MIN_5M_VOLUME_SURGE_RATIO and
                    pct_5m <= -config.MIN_5M_PRICE_IMPULSE_PCT and
                    upper_wick >= config.WICK_REJECTION_MIN and
                    lower_wick <= config.WICK_EXHAUSTION_MAX and
                    config.STOP_LOSS_MIN_PCT <= sl_short_dist <= config.STOP_LOSS_MAX_PCT and
                    not btc_regime.get("is_pumping", False)
                )

                if not is_long and not is_short:
                    return None

                side = "LONG" if is_long else "SHORT"
                chosen = {**t, **analysis, "candidate_side": side}

                # Оценка квантовой моделью
                ml_res = ml_engine.evaluate_candidate(chosen)
                chosen["ml_prob"] = ml_res.get("ml_probability", 0.5)
                chosen["ml_reason"] = ml_res.get("reason", "")
                chosen["ml_approved"] = ml_res.get("ml_approved", False)
                chosen["btc_regime"] = btc_regime.get("status_str", "Neutral")
                # Балл силы импульса как в бектесте: abs(pct_5m) * surge
                chosen["score"] = round(abs(pct_5m) * surge, 3)
                return chosen

        tasks = [check_ticker(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_scored = [r for r in results if r and isinstance(r, dict)]
        portfolio.funnel_stats["hard_gates"] += len(all_scored)

        # Сортируем кандидатов строго по силе импульса (как в бектесте)
        all_scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        portfolio.update_live_ml_ranking(all_scored)

        # Выводим лог лидеров квантового радара раз в минуту
        if should_log and all_scored:
            top_3 = all_scored[:3]
            top_str = ", ".join([f"{c['symbol']} {c['candidate_side']} (Score: {c['score']}, ML: {int(c['ml_prob']*100)}%)" for c in top_3])
            print(f"🔥 [A+ СЕКВЕНЦИЯ] Найдено {len(all_scored)} сетапов | Лидеры: {top_str}", flush=True)

        # 5. ОТБОР КАНДИДАТОВ ДЛЯ GROQ AI:
        # Оцениваем лучших кандидатов для заполнения свободных слотов портфеля
        free_slots = max(1, config.MAX_CONCURRENT_POSITIONS - len(portfolio.open_positions))
        candidates_to_eval = all_scored[:free_slots]

        # 6. GROQ SOFT GATE & ИСПОЛНЕНИЕ СДЕЛКИ
        for ctx in candidates_to_eval:
            sym = ctx["symbol"]
            cand_side = ctx.get("candidate_side", "LONG")
            portfolio.funnel_stats["groq_evaluated"] += 1
            self.cooldowns[sym] = now

            approved, groq_eval = await groq_engine.evaluate_setup(ctx)

            default_sl = ctx["wick_stop_loss"] if cand_side == "LONG" else ctx.get("short_wick_sl", ctx["current_price"] * 1.01)
            default_tp1 = round(ctx["current_price"] * (1.0 + config.TP1_PCT if cand_side == "LONG" else 1.0 - config.TP1_PCT), 4)

            eval_entry = {
                "symbol": sym,
                "side": cand_side,
                "price": ctx["current_price"],
                "decision": groq_eval.get("decision", "SKIP"),
                "confidence": groq_eval.get("confidence", 0.0),
                "ml_prob": round(ctx.get("ml_prob", 0.5) * 100, 1),
                "reason": groq_eval.get("reason", ""),
                "sl": groq_eval.get("stop_loss") or default_sl,
                "tp1": groq_eval.get("tp1") or default_tp1,
                "surge": ctx["volume_surge_ratio"],
                "score": ctx.get("score", 1.0),
                "pullback": round(ctx.get("pullback_from_high_pct", 0) * 100, 2) if cand_side == "LONG" else round(ctx.get("bounce_from_low_pct", 0) * 100, 2),
                "model": groq_eval.get("model", "unknown"),
                "finish_reason": groq_eval.get("finish_reason", "unknown"),
                "time": time.strftime("%H:%M:%S")
            }
            portfolio.add_evaluation(eval_entry)
            print(f"🤖 [GROQ JEV] {sym} ({cand_side}): {eval_entry['decision']} ({int(eval_entry['confidence']*100)}%) | {eval_entry['reason']}", flush=True)

            if approved:
                portfolio.funnel_stats["passed"] += 1

                if portfolio.is_daily_limit_reached():
                    print(f"🛑 [CIRCUIT BREAKER] Дневной лимит {config.DAILY_LOSS_LIMIT} убытка исчерпан. Защита депозита активна.", flush=True)
                    break

                entry_p = ctx["current_price"]
                wick_sl = eval_entry["sl"]

                min_tp1_dist = entry_p * config.TP1_PCT
                min_tp2_dist = entry_p * config.TP2_PCT

                if cand_side == "LONG":
                    risk_per_coin = max(entry_p - wick_sl, entry_p * 0.003)
                    tp1_2r = round(max(entry_p + (config.TARGET_1_R * risk_per_coin), entry_p + min_tp1_dist), 6)
                    tp2_3r = round(max(entry_p + (config.TARGET_2_R * risk_per_coin), entry_p + min_tp2_dist), 6)
                else:  # SHORT
                    risk_per_coin = max(wick_sl - entry_p, entry_p * 0.003)
                    tp1_2r = round(min(entry_p - (config.TARGET_1_R * risk_per_coin), entry_p - min_tp1_dist), 6)
                    tp2_3r = round(min(entry_p - (config.TARGET_2_R * risk_per_coin), entry_p - min_tp2_dist), 6)

                # ФИКСИРОВАННЫЙ РАЗМЕР МАРЖИ $5.00 (КАК В БЕКТЕСТЕ FIXED_5):
                # Равный вес риска, защита депозита от перегруза
                lev_to_use = getattr(portfolio, "current_leverage", config.LEVERAGE)
                actual_margin = round(min(config.TRADE_AMOUNT_USDT, portfolio.cash * 0.45), 2)

                # Проверка лимитов портфеля и открытие позиции
                if len(portfolio.open_positions) < config.MAX_CONCURRENT_POSITIONS and portfolio.cash >= actual_margin:
                    opened = portfolio.open_position(
                        symbol=sym,
                        side=cand_side,
                        entry_price=entry_p,
                        size_usdt=actual_margin,
                        wick_sl=wick_sl,
                        tp1=tp1_2r,
                        tp2=tp2_3r,
                        groq_reason=f"Selective A+ (Score: {ctx.get('score', 1.0)}) | {eval_entry['reason']}",
                        leverage=lev_to_use
                    )
                    if opened:
                        print(f"🟢 [TRADE OPEN] {cand_side} {sym} по ${entry_p:.4f} (Маржа: ${actual_margin:.2f}, Плечо: {lev_to_use}x) | SL: ${wick_sl:.4f} | TP1: ${tp1_2r:.4f}", flush=True)
                        break
            else:
                if groq_eval.get("decision") == "SKIP":
                    portfolio.funnel_stats["groq_skip"] = portfolio.funnel_stats.get("groq_skip", 0) + 1
                elif groq_eval.get("confidence", 0.0) < config.GROQ_MIN_CONFIDENCE:
                    portfolio.funnel_stats["low_conf"] = portfolio.funnel_stats.get("low_conf", 0) + 1

                portfolio.shadow_trades.insert(0, {
                    "symbol": sym,
                    "side": cand_side,
                    "rejected_at_price": ctx["current_price"],
                    "sl": eval_entry["sl"],
                    "tp1": eval_entry["tp1"],
                    "current_price": ctx["current_price"],
                    "price_change_pct": 0.0,
                    "outcome": "Ожидание хода...",
                    "reason": groq_eval.get("reason", "Отклонено Groq"),
                    "time": time.strftime("%H:%M:%S"),
                    "timestamp": time.time(),
                    "score": eval_entry.get("score", 1.0)
                })
                if len(portfolio.shadow_trades) > 50:
                    portfolio.shadow_trades = portfolio.shadow_trades[:50]
                portfolio.save()

                try:
                    obsidian_vault.log_shadow_decision(eval_entry)
                except Exception:
                    pass

        return candidates_to_eval

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
