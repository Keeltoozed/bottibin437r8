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
    Высокоскоростной автономный сканер структурных пробоев (Structural Rocket Hunter).
    Ищет выходы из многочасовых баз Дончиана (20 баров) с подтверждением RVOL >= 1.8x,
    сильным закрытием бара (CLV >= 0.68), честным структурным стопом и фиксированным риском в долларах!
    """
    def __init__(self):
        self.is_running = False
        self.cooldowns: Dict[str, float] = {}
        self._last_log_time = 0.0

    async def scan_market_once(self) -> List[Dict[str, Any]]:
        """Один параллельный проход сканирования рынка."""
        now = time.time()
        now_str = time.strftime("%H:%M:%S")
        portfolio.last_scan_str = now_str

        pause_until = getattr(portfolio, "pause_until", 0.0)
        if portfolio.is_paused or now < pause_until:
            rem = int(pause_until - now)
            if rem > 0:
                portfolio.btc_regime_str = f"🛑 Пауза Circuit Breaker ({rem} сек)"
            return []

        if portfolio.is_daily_limit_reached():
            portfolio.btc_regime_str = f"🛑 Дневной лимит убытков достигнут ({portfolio.daily_losses_count}/{config.DAILY_LOSS_LIMIT})"
            return []

        if len(portfolio.open_positions) >= config.MAX_CONCURRENT_POSITIONS:
            return []

        # 0. MACRO GUARD: Режим Bitcoin
        btc_regime = await binance_client.fetch_btc_regime()
        portfolio.btc_regime_str = btc_regime.get("status_str", "")

        # 1. UNIVERSE: Широкий радар пробоев (до 100 ликвидных пар)
        tickers = await binance_client.fetch_top_tickers(
            min_vol_usdt=config.MIN_24H_VOLUME_USDT,
            limit=config.SCAN_TICKERS_LIMIT
        )
        portfolio.funnel_stats["universe"] += len(tickers)

        should_log = (now - self._last_log_time) >= 60.0
        if should_log:
            self._last_log_time = now
            btc_p = btc_regime.get("pct_15m", 0.0)
            print(
                f"📡 [ROCKET RADAR] {now_str} — Мониторинг {len(tickers)} пар (Donchian Breakout + RVOL) | "
                f"BTC 15m: {btc_p:+.2f}% | Оценок Groq: {portfolio.funnel_stats['groq_evaluated']}",
                flush=True
            )

        await binance_client.fetch_all_book_tickers()
        sem = asyncio.Semaphore(16)

        async def check_ticker(t: Dict[str, Any]) -> Any:
            sym = t["symbol"]

            strict = getattr(config, "STRICT_WHITELIST_ONLY", False)
            if strict and sym not in getattr(config, "TOP_CRYPTO_UNIVERSE", []):
                return None
            if sym in getattr(config, "EXCLUDED_TICKERS", set()):
                return None

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
                # 2. HARD GATE: Узкий спред в стакане
                _, _, spread = await binance_client.fetch_orderbook_spread(sym)
                if spread > config.MAX_SPREAD_PCT:
                    portfolio.funnel_stats["gate_failed"] = portfolio.funnel_stats.get("gate_failed", 0) + 1
                    return None

                # 3. Структурный 5m свечной анализ (80 свечей)
                analysis = await binance_client.fetch_candles_analysis(sym, interval="5m", limit=80)
                if not analysis:
                    return None

                pct_5m = analysis.get("pct_5m", 0.0)
                surge = analysis.get("volume_surge_ratio", 1.0)
                upper_wick = analysis.get("upper_wick_pct", 0.0)
                lower_wick = analysis.get("lower_wick_pct", 0.0)
                clv_long = analysis.get("close_strength_long", 0.5)
                clv_short = analysis.get("close_strength_short", 0.5)
                sig_close = analysis.get("signal_close", analysis["current_price"])
                ema9 = analysis.get("ema9", sig_close)
                ema21 = analysis.get("ema21", sig_close)
                rsi = analysis.get("rsi", 50.0)
                atr_pct = analysis.get("atr14_pct", 0.005)
                ema21_ext = analysis.get("ema21_ext_pct", 0.0)
                sl_long_dist = analysis.get("sl_pct_distance", 0.01)
                sl_short_dist = analysis.get("short_sl_dist", 0.01)

                min_req_impulse = max(config.MIN_5M_PRICE_IMPULSE_PCT, atr_pct * 100.0 * 0.90)

                # ==============================================================
                # 4. ПРАВИЛА ВХОДА STRUCTURAL ROCKET HUNTER (LONG & SHORT)
                # - Подтвержденный пробой 20-барного уровня Дончиана (или 12-барный Ignition при RVOL >= 2.8x)
                # - Реальный взрыв объема RVOL >= 1.80x
                # - Сильное закрытие свечи у экстремума (CLV >= 0.68, Marubozu проходят на 100%!)
                # - Встречный фитиль <= 28% (защита от Bull/Bear Trap)
                # - Выравнивание EMA9/EMA21 без поздней перерастяжки (>3.5% от EMA21 отсекается)
                # - Честный структурный стоп 0.50%..2.20%
                # ==============================================================
                is_long = (
                    analysis.get("is_breakout_long", False) and
                    surge >= config.MIN_5M_VOLUME_SURGE_RATIO and
                    pct_5m >= min_req_impulse and
                    clv_long >= config.MIN_CLOSE_STRENGTH and
                    upper_wick <= config.WICK_EXHAUSTION_MAX and
                    sig_close > ema9 and ema9 >= ema21 * 0.998 and
                    config.MIN_RSI_LONG <= rsi <= config.MAX_RSI_LONG and
                    ema21_ext <= config.MAX_EMA21_EXTENSION_PCT and
                    analysis.get("live_drift_long_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT and
                    not analysis.get("breakout_failed_long", False) and
                    config.STOP_LOSS_MIN_PCT <= sl_long_dist <= config.STOP_LOSS_MAX_PCT and
                    not btc_regime.get("is_dumping", False)
                )

                is_short = (
                    config.ENABLE_SHORT and
                    analysis.get("is_breakout_short", False) and
                    surge >= config.MIN_5M_VOLUME_SURGE_RATIO and
                    pct_5m <= -min_req_impulse and
                    clv_short >= config.MIN_CLOSE_STRENGTH and
                    lower_wick <= config.WICK_EXHAUSTION_MAX and
                    sig_close < ema9 and ema9 <= ema21 * 1.002 and
                    config.MIN_RSI_SHORT <= rsi <= config.MAX_RSI_SHORT and
                    ema21_ext <= config.MAX_EMA21_EXTENSION_PCT and
                    analysis.get("live_drift_short_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT and
                    not analysis.get("breakout_failed_short", False) and
                    config.STOP_LOSS_MIN_PCT <= sl_short_dist <= config.STOP_LOSS_MAX_PCT and
                    not btc_regime.get("is_pumping", False)
                )

                if not is_long and not is_short:
                    portfolio.funnel_stats["gate_failed"] = portfolio.funnel_stats.get("gate_failed", 0) + 1
                    return None

                side = "LONG" if is_long else "SHORT"
                clv_used = clv_long if side == "LONG" else clv_short
                chosen = {**t, **analysis, "candidate_side": side}

                # Оценка квантовой моделью строго по закрытой сигнальной свече
                ml_res = ml_engine.evaluate_candidate(chosen)
                chosen["ml_prob"] = ml_res.get("ml_probability", 0.5)
                chosen["ml_reason"] = ml_res.get("reason", "")
                chosen["ml_approved"] = ml_res.get("ml_approved", False)
                chosen["btc_regime"] = btc_regime.get("status_str", "Neutral")

                min_ml = float(getattr(config, "ML_MIN_FILTER_PROB", 0.42))
                if ml_res.get("ml_active") and chosen["ml_prob"] < min_ml:
                    portfolio.funnel_stats["gate_failed"] = portfolio.funnel_stats.get("gate_failed", 0) + 1
                    return None

                ml_mult = (0.5 + chosen["ml_prob"]) if ml_res.get("ml_active") else 1.0
                chosen["score"] = round(abs(pct_5m) * surge * clv_used * ml_mult, 3)
                return chosen

        tasks = [check_ticker(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_scored = [r for r in results if r and isinstance(r, dict)]
        portfolio.funnel_stats["hard_gates"] += len(all_scored)

        all_scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        portfolio.update_live_ml_ranking(all_scored)

        if should_log and all_scored:
            top_3 = all_scored[:3]
            top_str = ", ".join([
                f"{c['symbol']} {c['candidate_side']} (Score: {c['score']}, RVOL: {c['volume_surge_ratio']}x, ML: {int(c['ml_prob']*100)}%)"
                for c in top_3
            ])
            print(f"🚀 [ПРОБОЙ НАЙДЕН] Кандидатов: {len(all_scored)} | Лидеры: {top_str}", flush=True)

        # 5. ОТБОР ЛУЧШИХ КАНДИДАТОВ ДЛЯ GROQ AI
        free_slots = max(1, config.MAX_CONCURRENT_POSITIONS - len(portfolio.open_positions))
        candidates_to_eval = all_scored[:free_slots]

        # 6. GROQ SOFT GATE & RISK-BASED POSITION SIZING
        for ctx in candidates_to_eval:
            sym = ctx["symbol"]
            cand_side = ctx.get("candidate_side", "LONG")
            portfolio.funnel_stats["groq_evaluated"] += 1
            self.cooldowns[sym] = now

            approved, groq_eval = await groq_engine.evaluate_setup(ctx)

            entry_p = ctx["current_price"]
            if cand_side == "LONG":
                exact_sl = ctx.get("wick_stop_loss", round(entry_p * 0.990, 6))
                risk_per_coin = max(entry_p - exact_sl, entry_p * config.STOP_LOSS_MIN_PCT)
                tp1_target = round(entry_p + max(config.TARGET_1_R * risk_per_coin, entry_p * config.TP1_PCT), 6)
                tp2_target = round(entry_p + max(config.TARGET_2_R * risk_per_coin, entry_p * config.TP2_PCT), 6)
            else:
                exact_sl = ctx.get("short_wick_stop_loss", round(entry_p * 1.010, 6))
                risk_per_coin = max(exact_sl - entry_p, entry_p * config.STOP_LOSS_MIN_PCT)
                tp1_target = round(entry_p - max(config.TARGET_1_R * risk_per_coin, entry_p * config.TP1_PCT), 6)
                tp2_target = round(entry_p - max(config.TARGET_2_R * risk_per_coin, entry_p * config.TP2_PCT), 6)

            eval_entry = {
                "symbol": sym,
                "side": cand_side,
                "price": entry_p,
                "decision": groq_eval.get("decision", "SKIP"),
                "confidence": groq_eval.get("confidence", 0.0),
                "ml_prob": round(ctx.get("ml_prob", 0.5) * 100, 1),
                "reason": groq_eval.get("reason", ""),
                "sl": exact_sl,
                "tp1": tp1_target,
                "surge": ctx["volume_surge_ratio"],
                "score": ctx.get("score", 1.0),
                "pullback": round(ctx.get("live_drift_long_pct", 0) * 100, 2) if cand_side == "LONG" else round(ctx.get("live_drift_short_pct", 0) * 100, 2),
                "model": groq_eval.get("model", "unknown"),
                "finish_reason": groq_eval.get("finish_reason", "unknown"),
                "time": time.strftime("%H:%M:%S")
            }
            portfolio.add_evaluation(eval_entry)
            print(f"🤖 [GROQ JEV] {sym} ({cand_side}): {eval_entry['decision']} ({int(eval_entry['confidence']*100)}%) | {eval_entry['reason']}", flush=True)

            if approved:
                portfolio.funnel_stats["passed"] += 1

                if portfolio.is_daily_limit_reached():
                    print(f"🛑 [CIRCUIT BREAKER] Дневной лимит {config.DAILY_LOSS_LIMIT} убытка исчерпан.", flush=True)
                    break

                # ПРОФЕССИОНАЛЬНЫЙ ФИКСИРОВАННЫЙ ДОЛЛАРОВЫЙ РИСК (PROP-DESK SIZING):
                # Независимо от ширины структурного стопа (0.6% или 1.8%), максимальный риск на сделку
                # фиксирован (~2.5% эквити = $0.50 при $20 депозите с учетом комиссий 0.12%!)
                cur_equity = max(15.0, portfolio.get_portfolio_summary()["equity"])
                risk_usd = round(cur_equity * config.RISK_PER_TRADE_PCT, 3)
                sl_dist_pct = abs(entry_p - exact_sl) / max(entry_p, 1e-9)
                lev_to_use = getattr(portfolio, "current_leverage", config.LEVERAGE)

                target_notional = risk_usd / (sl_dist_pct + 0.0012)
                actual_margin = round(min(target_notional / lev_to_use, portfolio.cash * 0.45), 2)

                if len(portfolio.open_positions) < config.MAX_CONCURRENT_POSITIONS and actual_margin >= 1.50 and portfolio.cash >= actual_margin:
                    opened = portfolio.open_position(
                        symbol=sym,
                        side=cand_side,
                        entry_price=entry_p,
                        size_usdt=actual_margin,
                        wick_sl=exact_sl,
                        tp1=tp1_target,
                        tp2=tp2_target,
                        groq_reason=f"Rocket Breakout (Score: {ctx.get('score', 1.0)}, RVOL: {ctx['volume_surge_ratio']}x) | {eval_entry['reason']}",
                        leverage=lev_to_use,
                        atr_pct=ctx.get("atr14_pct", 0.006),
                        risk_usd=risk_usd
                    )
                    if opened:
                        print(
                            f"🟢 [ROCKET OPEN] {cand_side} {sym} по ${entry_p:.4f} | "
                            f"Маржа: ${actual_margin:.2f} ({lev_to_use}x, Риск 1R: ${risk_usd:.2f}) | "
                            f"SL: ${exact_sl:.4f} ({sl_dist_pct*100:.2f}%) | TP1(1.5R): ${tp1_target:.4f} | TP2(3R): ${tp2_target:.4f}",
                            flush=True
                        )
                        if len(portfolio.open_positions) >= config.MAX_CONCURRENT_POSITIONS:
                            break
            else:
                if groq_eval.get("decision") == "SKIP":
                    portfolio.funnel_stats["groq_skip"] = portfolio.funnel_stats.get("groq_skip", 0) + 1
                elif groq_eval.get("confidence", 0.0) < config.GROQ_MIN_CONFIDENCE:
                    portfolio.funnel_stats["low_conf"] = portfolio.funnel_stats.get("low_conf", 0) + 1

                portfolio.shadow_trades.insert(0, {
                    "symbol": sym,
                    "side": cand_side,
                    "rejected_at_price": entry_p,
                    "sl": eval_entry["sl"],
                    "tp1": eval_entry["tp1"],
                    "current_price": entry_p,
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
        print(f"📡 [MarketScanner] Автономный радар ракет запущен (Интервал: {config.SCAN_INTERVAL_SECONDS}с, {config.SCAN_TICKERS_LIMIT} пар, LONG+SHORT)...", flush=True)
        while self.is_running:
            try:
                await self.scan_market_once()
            except Exception as e:
                print(f"⚠️ Ошибка в MarketScanner: {e}", flush=True)
            await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)

market_scanner = MarketScanner()
