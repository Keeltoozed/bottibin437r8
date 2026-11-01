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
            print(f"📡 [РАДАР] {now_str} — Мониторинг {len(tickers)} пар Binance (Ракеты + Ликвидность) | BTC: {btc_p:+.2f}% | Оценок Groq: {portfolio.funnel_stats['groq_evaluated']}", flush=True)

        # Предварительно загружаем стаканы всех пар за 1 сетевой вызов
        await binance_client.fetch_all_book_tickers()
        sem = asyncio.Semaphore(16)  # 16 параллельных потоков для высокой скорости

        async def check_ticker(t: Dict[str, Any]) -> Any:
            sym = t["symbol"]

            # Проверка белого и черного списков
            strict = getattr(config, "STRICT_WHITELIST_ONLY", False)
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

                # 3. Получаем 5m свечной анализ (80 свечей для расчета EMA50, RSI14, ATR)
                analysis = await binance_client.fetch_candles_analysis(sym, interval="5m", limit=80)
                if not analysis:
                    return None

                # 4. НЕПРЕРЫВНЫЙ КВАНТОВЫЙ ML СКОРИНГ КАЖДОЙ ПАРЫ (Dual XGBoost Alpha):
                # Оцениваем монету на 30 институциональных факторов под режимы LONG и SHORT
                cand_long = {**t, **analysis, "candidate_side": "LONG"}
                cand_short = {**t, **analysis, "candidate_side": "SHORT"}

                btc_dump = btc_regime.get("is_dumping", False)
                btc_pump = btc_regime.get("is_pumping", False)

                if btc_dump:
                    # Рынок падает: оцениваем строго SHORT сетапы
                    chosen = cand_short
                    ml_res = ml_engine.evaluate_candidate(cand_short)
                    side = "SHORT"
                elif btc_pump:
                    # Рынок растет: оцениваем строго LONG сетапы
                    chosen = cand_long
                    ml_res = ml_engine.evaluate_candidate(cand_long)
                    side = "LONG"
                else:
                    # Боковик: оцениваем оба направления и выбираем наивысшую вероятность
                    res_l = ml_engine.evaluate_candidate(cand_long)
                    res_s = ml_engine.evaluate_candidate(cand_short)
                    if res_s.get("ml_probability", 0.0) > res_l.get("ml_probability", 0.0):
                        chosen = cand_short
                        ml_res = res_s
                        side = "SHORT"
                    else:
                        chosen = cand_long
                        ml_res = res_l
                        side = "LONG"

                chosen["candidate_side"] = side
                chosen["ml_prob"] = ml_res.get("ml_probability", 0.5)
                chosen["ml_reason"] = ml_res.get("reason", "")
                chosen["ml_approved"] = ml_res.get("ml_approved", False)
                chosen["btc_regime"] = btc_regime.get("status_str", "Neutral")
                return chosen

        tasks = [check_ticker(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_scored = [r for r in results if r and isinstance(r, dict)]
        portfolio.funnel_stats["hard_gates"] += len(all_scored)

        # Сохраняем полный живой рейтинг всех пар рынка в портфель
        all_scored.sort(key=lambda x: x.get("ml_prob", 0.0), reverse=True)
        portfolio.update_live_ml_ranking(all_scored)

        # Выводим лог лидеров квантового радара раз в минуту
        if should_log and all_scored:
            top_3 = all_scored[:3]
            top_str = ", ".join([f"{c['symbol']} {c['candidate_side']} ({int(c['ml_prob']*100)}%)" for c in top_3])
            print(f"🧠 [QUANT ML] Все {len(all_scored)} пар оценены | Топ: {top_str} | Порог входа: {int(ml_engine.threshold*100)}%", flush=True)

        # 5. ОТБОР КАНДИДАТОВ ДЛЯ GROQ AI (A+ СЕКВЕНЦИЯ):
        # Только монеты с подтвержденным математическим перевесом ML и строгим риск-профилем
        candidates_to_eval = []
        for cand in all_scored:
            sym = cand["symbol"]
            side = cand["candidate_side"]
            prob = cand["ml_prob"]
            sl_dist = cand["sl_pct_distance"] if side == "LONG" else cand.get("short_sl_dist", 0.05)
            surge = cand.get("volume_surge_ratio", 1.0)
            pct_5m = cand.get("pct_5m", 0.0)

            # Требуем подтвержденный перевес квантовой модели
            min_ml_thresh = getattr(config, "ML_CONFIDENCE_THRESHOLD", 0.68)
            if prob < min_ml_thresh:
                continue

            # Защита от опасных стопов (не более 0.75% для 60x плеча)
            if sl_dist > config.MAX_ALLOWED_SL_PCT:
                if should_log:
                    print(f"🛑 [СТОП-ФИЛЬТР] {sym} ({side}) ML {int(prob*100)}% отклонен: стоп {sl_dist*100:.2f}% > {config.MAX_ALLOWED_SL_PCT*100:.2f}% (риск -{int(sl_dist*config.LEVERAGE*100)}% маржи при {config.LEVERAGE}x)", flush=True)
                continue

            # Проверка BTC-фильтра (Directional Lock)
            if side == "LONG" and btc_regime.get("is_dumping", False):
                portfolio.funnel_stats["btc_blocked"] = portfolio.funnel_stats.get("btc_blocked", 0) + 1
                if should_log:
                    print(f"🛑 [BTC БЛОК] {sym} LONG ML {int(prob*100)}% отклонен: BTC падает — ЛОНГИ ЗАБЛОКИРОВАНЫ", flush=True)
                continue
            if side == "SHORT" and btc_regime.get("is_pumping", False):
                portfolio.funnel_stats["btc_blocked"] = portfolio.funnel_stats.get("btc_blocked", 0) + 1
                if should_log:
                    print(f"🛑 [BTC БЛОК] {sym} SHORT ML {int(prob*100)}% отклонен: BTC растет — ШОРТЫ ЗАБЛОКИРОВАНЫ", flush=True)
                continue

            # Проверка минимальной активности (не спим в мертвом стакане)
            if surge < 1.30 and abs(pct_5m) < 0.30:
                if should_log:
                    print(f"🛑 [НЕТ ИМПУЛЬСА] {sym} ({side}) ML {int(prob*100)}% отклонен: всплеск {surge:.2f}x < 1.30x и ход 5m {pct_5m:+.2f}% < 0.30%", flush=True)
                continue

            # Защита от контртрендовых сделок (Мульти-таймфрейм 5m + 15m Trend Alignment)
            trend = cand.get("trend", "CHOP")
            pct_15m = cand.get("pct_15m", 0.0)
            if side == "SHORT" and (trend == "BULLISH" or pct_5m > 0.40 or pct_15m > 0.40):
                if should_log:
                    print(f"🛑 [ТРЕНД-БЛОК] {sym} SHORT ML {int(prob*100)}% отклонен: монета растет (5m: {pct_5m:+.2f}%, 15m: {pct_15m:+.2f}%)", flush=True)
                continue
            if side == "LONG" and (trend == "BEARISH" or pct_5m < -0.40 or pct_15m < -0.40):
                if should_log:
                    print(f"🛑 [ТРЕНД-БЛОК] {sym} LONG ML {int(prob*100)}% отклонен: монета падает (5m: {pct_5m:+.2f}%, 15m: {pct_15m:+.2f}%)", flush=True)
                continue

            # Защита от распила в боковике BTC (CHOP Shield):
            # В боковике BTC 80% альткоин-пробоев ложные. Входим ТОЛЬКО при мощном взрыве объема (от 2.5x) и уверенности ML от 75%
            is_btc_chop = not btc_regime.get("is_dumping", False) and not btc_regime.get("is_pumping", False)
            chop_min_surge = getattr(config, "CHOP_MIN_VOLUME_SURGE", 2.50)
            if is_btc_chop and (surge < chop_min_surge or prob < 0.75):
                if should_log:
                    print(f"🛑 [CHOP БЛОК] {sym} ({side}) отклонен: BTC в боковике — требуется взрыв объема >={chop_min_surge:.1f}x (факт: {surge:.2f}x) и ML >= 75% (факт: {int(prob*100)}%)", flush=True)
                continue

            candidates_to_eval.append(cand)
            print(f"🔥 [A+ КАНДИДАТ - {side}] {sym}: ML {int(prob*100)}%, всплеск {surge:.2f}x, 5m: {pct_5m:+.2f}% | Передача в Groq AI...", flush=True)

        # Фокусируемся на абсолютном лидере
        candidates_to_eval = candidates_to_eval[:1]

        # 4. GROQ SOFT GATE (JEV AI ENGINE)
        for ctx in candidates_to_eval:
            sym = ctx["symbol"]
            cand_side = ctx.get("candidate_side", "LONG")
            portfolio.funnel_stats["groq_evaluated"] += 1
            # КУЛДАУН: ставится ТОЛЬКО монете, которая реально отправлена на оценку в Groq (без блокировки остальных!)
            self.cooldowns[sym] = now

            approved, groq_eval = await groq_engine.evaluate_setup(ctx)

            default_sl = ctx["wick_stop_loss"] if cand_side == "LONG" else ctx.get("short_wick_sl", ctx["current_price"] * 1.01)
            default_tp1 = round(ctx["current_price"] * (1.02 if cand_side == "LONG" else 0.98), 4)

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
                "pullback": round(ctx.get("pullback_from_high_pct", 0) * 100, 2) if cand_side == "LONG" else round(ctx.get("bounce_from_low_pct", 0) * 100, 2),
                "model": groq_eval.get("model", "unknown"),
                "finish_reason": groq_eval.get("finish_reason", "unknown"),
                "time": time.strftime("%H:%M:%S")
            }
            portfolio.add_evaluation(eval_entry)
            print(f"🤖 [GROQ JEV] {sym} ({cand_side}): {eval_entry['decision']} ({int(eval_entry['confidence']*100)}%) | {eval_entry['reason']}", flush=True)

            if approved:
                portfolio.funnel_stats["passed"] += 1

                # 1. Проверка дневного лимита Circuit Breaker (если включен)
                if getattr(config, "ENABLE_CIRCUIT_BREAKER", False) and portfolio.get_daily_loss() >= config.MAX_DAILY_LOSS_USD:
                    print(f"🛑 [CIRCUIT BREAKER] Дневной лимит убытка (-${portfolio.get_daily_loss():.2f}) исчерпан. Защита депозита активна.", flush=True)
                    continue

                entry_p = ctx["current_price"]
                wick_sl = eval_entry["sl"]

                # Минимальное расстояние тейк-профитов для защиты от микро-сделок:
                # TP1: минимум 1.5% хода цены (+90.0% ROI при 60x)
                # TP2: минимум 3.0% хода цены (+180.0% ROI при 60x)
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

                # 2. ИНСТИТУЦИОНАЛЬНЫЙ РАСЧЕТ РАЗМЕРА ОТ СТОП-ЛОССА (TRUE RISK-BASED SIZING):
                # Маржа подбирается математически так, чтобы при срабатывании стопа терялась ровно сумма risk_usd (10% от депо)
                lev_to_use = getattr(portfolio, "current_leverage", config.LEVERAGE)
                risk_pct = getattr(config, "COMPOUND_RISK_PCT", 0.10) if config.ENABLE_COMPOUNDING else 0.10
                risk_usd = max(portfolio.cash * risk_pct, config.MAX_RISK_PER_TRADE_USD)

                # Реальное расстояние до стопа (не менее 0.3% для безопасности)
                stop_dist_pct = max(risk_per_coin / entry_p, 0.003)

                # Формула: margin = risk_usd / (stop_dist_pct * leverage)
                calc_margin = risk_usd / (stop_dist_pct * lev_to_use)

                # Потолок: не более 45% от баланса портфеля и не менее $3.00 (минимальный лот биржи)
                actual_margin = round(min(max(calc_margin, 3.0), portfolio.cash * 0.45), 2)

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
                if groq_eval.get("decision") == "SKIP":
                    portfolio.funnel_stats["groq_skip"] = portfolio.funnel_stats.get("groq_skip", 0) + 1
                elif groq_eval.get("confidence", 0.0) < config.GROQ_MIN_CONFIDENCE:
                    portfolio.funnel_stats["low_conf"] = portfolio.funnel_stats.get("low_conf", 0) + 1

                # Сохраняем в Shadow Tracker для анализа отклонённых сетапов
                portfolio.shadow_trades.insert(0, {
                    "symbol": sym,
                    "side": cand_side,
                    "rejected_at_price": ctx["current_price"],
                    "current_price": ctx["current_price"],
                    "price_change_pct": 0.0,
                    "outcome": "Ожидание хода...",
                    "reason": eval_entry["reason"],
                    "time": time.strftime("%H:%M:%S"),
                    "timestamp": time.time(),
                    "score": eval_entry["confidence"]
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
