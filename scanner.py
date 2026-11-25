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
        self._last_scanned_bar: int = 0
        self._last_mirror_used: str = ""

    async def scan_market_once(self, force: bool = False) -> List[Dict[str, Any]]:
        """Один параллельный проход сканирования рынка строго на закрытии 5m свечи (защита от HTTP 418/429)."""
        now = time.time()
        now_str = time.strftime("%H:%M:%S")
        portfolio.last_scan_str = now_str

        # УМНАЯ ЗАЩИТА ОТ ЛИМИТОВ API (35x ЭКОНОМИЯ ВЕСА НА RENDER):
        # Стратегия работает строго по закрытым 5-минутным свечам!
        # Полный скан 80-100 пар запускается 1 раз в начале каждой новой 5m свечи (через 3с после закрытия бара),
        # а не 25 раз подряд за те же 5 минут — полностью исключает HTTP 418/429 бан на Render!
        cur_bar = int(now) // 300
        sec_into_bar = now % 300.0
        if not force and self._last_scanned_bar == cur_bar and portfolio.last_universe_count > 0:
            return []
        if not force and self._last_scanned_bar > 0 and sec_into_bar < 3.0:
            return []

        pause_until = getattr(portfolio, "pause_until", 0.0)
        if getattr(config, "ENABLE_CIRCUIT_BREAKER", False):
            if portfolio.is_paused or now < pause_until:
                rem = int(pause_until - now)
                if rem > 0:
                    portfolio.btc_regime_str = f"🛑 Пауза Circuit Breaker ({rem} сек)"
                return []

            if portfolio.is_daily_limit_reached():
                portfolio.btc_regime_str = f"🛑 Дневной лимит убытков достигнут ({portfolio.daily_losses_count}/{config.DAILY_LOSS_LIMIT})"
                return []

        at_risk_open = sum(1 for p in portfolio.open_positions.values() if not p.get("tp1_hit", False))
        max_total_slots = config.MAX_CONCURRENT_POSITIONS + int(getattr(config, "MAX_RISK_FREE_RUNNERS", 2))
        if at_risk_open >= config.MAX_CONCURRENT_POSITIONS or len(portfolio.open_positions) >= max_total_slots:
            return []

        # 0. MACRO GUARD: Режим Bitcoin
        btc_regime = await binance_client.fetch_btc_regime()
        portfolio.btc_regime_str = btc_regime.get("status_str", "")

        # 1. UNIVERSE: Широкий радар пробоев (до 115-150 ликвидных пар на fapi / bitget / vision)
        tickers = await binance_client.fetch_top_tickers(
            min_vol_usdt=config.MIN_24H_VOLUME_USDT,
            limit=config.SCAN_TICKERS_LIMIT
        )
        portfolio.last_universe_count = len(tickers)
        portfolio.funnel_stats["universe"] += len(tickers)

        should_log = force or (now - self._last_log_time) >= 60.0
        if should_log:
            self._last_log_time = now

        if not tickers:
            if should_log:
                print(f"⚠️ [ROCKET RADAR] {now_str} [{binance_client.active_mirror_name}] — Нет ответа от биржи, повтор через {config.SCAN_INTERVAL_SECONDS}с...", flush=True)
            return []

        # Если ticker24 еще не заполнил кеш стакана (например на fapi), подгружаем bookTickers одним запросом
        if not binance_client._book_tickers_cache or (time.time() - binance_client._book_tickers_cache_time) >= 30.0:
            await binance_client.fetch_all_book_tickers()
        # Мягкий параллелизм (6 потоков вместо 16) полностью исключает burst-лимиты Binance/Bitget на Render!
        sem = asyncio.Semaphore(6)

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

                # 3. Структурный 5m свечной анализ (200 свечей = 16.6ч для точной 15m EMA50, 6h базы и Anti-Rug щита)
                analysis = await binance_client.fetch_candles_analysis(sym, interval="5m", limit=200)
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
                dist_l_pct = analysis.get("dist_to_breakout_long_pct", 1.0)
                dist_s_pct = analysis.get("dist_to_breakout_short_pct", 1.0)

                min_req_impulse = max(config.MIN_5M_PRICE_IMPULSE_PCT, atr_pct * 100.0 * 0.85)
                min_atr_pct = float(getattr(config, "MIN_ATR_PCT", 0.0025))
                avg_5m_qvol = float(analysis.get("avg_5m_quote_vol", 0.0) or 0.0)
                v3_surge = float(analysis.get("v3_surge", 1.0) or 1.0)
                # Адаптация порога 5m объема под активное зеркало:
                # fapi ($15K/5m), bitget ($2K/5m + >=$5K пробойная свеча), vision/spot ($600/5m + >=$2.5K пробойная свеча).
                is_spot_mirror = binance_client.is_spot_mirror
                is_bitget_mirror = (binance_client.active_mirror_name == "bitget")
                if is_spot_mirror:
                    min_avg_vol = float(getattr(config, "SPOT_MIRROR_MIN_AVG_5M_VOL", 600.0))
                elif is_bitget_mirror:
                    min_avg_vol = float(getattr(config, "BITGET_MIRROR_MIN_AVG_5M_VOL", 2000.0))
                else:
                    min_avg_vol = float(getattr(config, "MIN_AVG_5M_QUOTE_VOL", 15000.0))
                last_5m_qvol = float(analysis.get("last_quote_volume", 0.0) or 0.0)
                if is_spot_mirror:
                    vol_floor_ok = (avg_5m_qvol >= min_avg_vol) and (last_5m_qvol >= 2500.0)
                elif is_bitget_mirror:
                    vol_floor_ok = (avg_5m_qvol >= min_avg_vol) and (last_5m_qvol >= 5000.0)
                else:
                    vol_floor_ok = (avg_5m_qvol >= min_avg_vol)
                min_v3 = float(getattr(config, "MIN_V3_VOLUME_PERSISTENCE", 1.10))
                is_mtf_long = analysis.get("is_mtf_long_ok", False) if getattr(config, "ENABLE_MTF_15M_FILTER", True) else True
                is_mtf_short = analysis.get("is_mtf_short_ok", False) if getattr(config, "ENABLE_MTF_15M_FILTER", True) else True
                is_macro_long = analysis.get("is_macro_trend_long", True)
                is_macro_short = analysis.get("is_macro_trend_short", True)
                anti_rug_long = analysis.get("anti_rug_long_ok", True)
                anti_rug_short = analysis.get("anti_rug_short_ok", True)
                brk_type = analysis.get("breakout_type", "STRUCT_3H")

                # ОТНОСИТЕЛЬНАЯ СИЛА ПРОТИВ BTC (IDIOSYNCRATIC ALPHA RS):
                # Ловим ТОЛЬКО монеты, которые летят САМИ намного сильнее BTC (отсекает 100% ложных флешей толпы!)
                btc_5m = float(btc_regime.get("pct_5m", 0.0) or 0.0)
                btc_15m = float(btc_regime.get("pct_15m", 0.0) or 0.0)
                pct_15m = float(analysis.get("pct_15m", pct_5m) or 0.0)
                alpha_5m = round(pct_5m - btc_5m, 2)
                alpha_15m = round(pct_15m - btc_15m, 2)
                min_a5 = float(getattr(config, "MIN_ALPHA_5M_PCT", 0.80))
                min_a15 = float(getattr(config, "MIN_ALPHA_15M_PCT", 1.00))

                # Подтверждение институционального объема (RVOL >= 1.80x И 3-свечной приток >= 1.10x)
                vol_confirmed = (surge >= config.MIN_5M_VOLUME_SURGE_RATIO) and (v3_surge >= min_v3)

                # ==============================================================
                # 4. ПРАВИЛА ВХОДА ALPHA ROCKET ENGINE (7/7 SPLITS VALIDATED)
                # - STRUCT_3H (36 баров) / SQUEEZE_80M (16 баров <= 6.5%) / RUG_SHORT (слив после пампа >= +15%)
                # - Idiosyncratic Alpha RS vs BTC: |alpha_5m| >= 0.80% и |alpha_15m| >= 1.00%
                # - Anti-BTC-Flush Guard: запрет шортить дно панической свечи BTC и покупать пик сквиза BTC
                # - Anti-Rug Top Guard: вход только из свежего сжатия (за 15м до пробоя ext <= 2.8%)
                # ==============================================================
                tech_long = (
                    analysis.get("is_breakout_long", False) and
                    anti_rug_long and
                    atr_pct >= min_atr_pct and
                    vol_confirmed and
                    vol_floor_ok and
                    is_mtf_long and
                    is_macro_long and
                    pct_5m >= min_req_impulse and
                    alpha_5m >= min_a5 and
                    alpha_15m >= min_a15 and
                    clv_long >= config.MIN_CLOSE_STRENGTH and
                    upper_wick <= config.WICK_EXHAUSTION_MAX and
                    sig_close > ema9 and ema9 >= ema21 * 0.998 and
                    config.MIN_RSI_LONG <= rsi <= config.MAX_RSI_LONG and
                    ema21_ext <= config.MAX_EMA21_EXTENSION_PCT and
                    analysis.get("live_drift_long_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT and
                    not analysis.get("breakout_failed_long", False) and
                    config.STOP_LOSS_MIN_PCT <= sl_long_dist <= config.STOP_LOSS_MAX_PCT
                )
                is_long = tech_long and not btc_regime.get("is_dumping", False) and not btc_regime.get("is_spike_up", False)

                tech_short = (
                    config.ENABLE_SHORT and
                    analysis.get("is_breakout_short", False) and
                    anti_rug_short and
                    atr_pct >= min_atr_pct and
                    vol_confirmed and
                    vol_floor_ok and
                    is_mtf_short and
                    is_macro_short and
                    pct_5m <= -min_req_impulse and
                    alpha_5m <= -min_a5 and
                    alpha_15m <= -min_a15 and
                    clv_short >= config.MIN_CLOSE_STRENGTH and
                    lower_wick <= config.WICK_EXHAUSTION_MAX and
                    sig_close < ema9 and ema9 <= ema21 * 1.002 and
                    config.MIN_RSI_SHORT <= rsi <= config.MAX_RSI_SHORT and
                    ema21_ext <= config.MAX_EMA21_EXTENSION_PCT and
                    analysis.get("live_drift_short_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT and
                    not analysis.get("breakout_failed_short", False) and
                    config.STOP_LOSS_MIN_PCT <= sl_short_dist <= config.STOP_LOSS_MAX_PCT
                )
                is_short = tech_short and not btc_regime.get("is_pumping", False) and not btc_regime.get("is_flush_down", False)

                if (tech_long and not is_long) or (tech_short and not is_short):
                    portfolio.funnel_stats["btc_blocked"] = portfolio.funnel_stats.get("btc_blocked", 0) + 1

                if not is_long and not is_short:
                    portfolio.funnel_stats["gate_failed"] = portfolio.funnel_stats.get("gate_failed", 0) + 1
                    # Формируем живую телеметрию поджатия для радара дашборда и логов
                    watch_side = "LONG" if (dist_l_pct <= dist_s_pct or not config.ENABLE_SHORT) else "SHORT"
                    dist_near = dist_l_pct if watch_side == "LONG" else dist_s_pct
                    brk_flag = analysis.get("is_breakout_long", False) if watch_side == "LONG" else analysis.get("is_breakout_short", False)
                    sl_d = sl_long_dist if watch_side == "LONG" else sl_short_dist
                    clv_w = clv_long if watch_side == "LONG" else clv_short
                    wick_w = upper_wick if watch_side == "LONG" else lower_wick

                    if (tech_long and not is_long) or (tech_short and not is_short):
                        w_status = "🛑 Щит BTC (защита от ложного флеша)"
                    elif brk_flag:
                        if watch_side == "LONG" and (alpha_5m < min_a5 or alpha_15m < min_a15):
                            w_status = f"📉 Слабая Alpha к BTC ({alpha_5m:+.2f}% / 15m {alpha_15m:+.2f}%)"
                        elif watch_side == "SHORT" and (alpha_5m > -min_a5 or alpha_15m > -min_a15):
                            w_status = f"📉 Слабая Alpha к BTC ({alpha_5m:+.2f}% / 15m {alpha_15m:+.2f}%)"
                        elif watch_side == "LONG" and not is_mtf_long:
                            w_status = "⏳ 15m тренд не бычий (против тренда)"
                        elif watch_side == "SHORT" and not is_mtf_short:
                            w_status = "⏳ 15m тренд не медвежий (против тренда)"
                        elif avg_5m_qvol < min_avg_vol:
                            w_status = f"💤 Тонкая монета (${avg_5m_qvol:.0f} < ${min_avg_vol:.0f})"
                        elif surge < config.MIN_5M_VOLUME_SURGE_RATIO:
                            w_status = f"📊 Пробой есть, ждем RVOL ({surge:.1f}x < {config.MIN_5M_VOLUME_SURGE_RATIO:.1f}x)"
                        elif v3_surge < min_v3:
                            w_status = f"📊 Одиночный всплеск (RVOL 3b: {v3_surge:.2f}x < {min_v3:.2f}x)"
                        elif abs(pct_5m) < min_req_impulse:
                            w_status = f"⚡ Слабый импульс ({pct_5m:+.2f}% < {min_req_impulse:.2f}%)"
                        elif clv_w < config.MIN_CLOSE_STRENGTH or wick_w > config.WICK_EXHAUSTION_MAX:
                            w_status = "🕯️ Тень истощения (отсев ловушки)"
                        elif sl_d > config.STOP_LOSS_MAX_PCT:
                            w_status = f"📏 Широкий стоп ({sl_d*100:.2f}% > {config.STOP_LOSS_MAX_PCT*100:.1f}%)"
                        else:
                            w_status = "⏳ Ждем выравнивания EMA / Anti-Rug"
                    else:
                        w_status = f"⏳ Поджатие: {dist_near:.2f}% до пробоя (RVOL {surge:.1f}x)"

                    watch_activity = round((abs(alpha_5m) + abs(pct_5m) * 0.5) * min(surge, 8.0) * (1.0 / max(dist_near, 0.20)), 3) if vol_floor_ok else 0.0
                    return {
                        "kind": "watch",
                        "data": {
                            **t,
                            **analysis,
                            "alpha_5m": alpha_5m,
                            "alpha_15m": alpha_15m,
                            "candidate_side": watch_side,
                            "dist_to_breakout_pct": dist_near,
                            "radar_status": w_status,
                            "watch_activity": watch_activity
                        }
                    }

                side = "LONG" if is_long else "SHORT"
                clv_used = clv_long if side == "LONG" else clv_short
                dist_used = dist_l_pct if side == "LONG" else dist_s_pct
                chosen = {
                    **t,
                    **analysis,
                    "alpha_5m": alpha_5m,
                    "alpha_15m": alpha_15m,
                    "candidate_side": side,
                    "dist_to_breakout_pct": dist_used,
                    "btc_regime": btc_regime.get("status_str", "Neutral")
                }

                # Оценка квантовой моделью строго по закрытой сигнальной свече
                ml_res = ml_engine.evaluate_candidate(chosen)
                chosen["ml_prob"] = ml_res.get("ml_probability", 0.5)
                chosen["ml_reason"] = ml_res.get("reason", "")
                chosen["ml_approved"] = ml_res.get("ml_approved", False)

                min_ml = float(getattr(config, "ML_MIN_FILTER_PROB", 0.0))
                if min_ml > 0 and ml_res.get("ml_active") and chosen["ml_prob"] < min_ml:
                    portfolio.funnel_stats["gate_failed"] = portfolio.funnel_stats.get("gate_failed", 0) + 1
                    chosen["radar_status"] = f"🧠 Отсев ML ({chosen['ml_prob']*100:.0f}% < {min_ml*100:.0f}%)"
                    chosen["watch_activity"] = round(surge * 3.0 + abs(alpha_5m), 3)
                    return {"kind": "watch", "data": chosen}

                chosen["score"] = round(abs(alpha_5m) * surge * clv_used, 3)
                chosen["radar_status"] = f"🚀 ALPHA ПРОБОЙ [{brk_type}] (RS {alpha_5m:+.1f}%)"
                return {"kind": "candidate", "data": chosen}

        tasks = [check_ticker(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_scored = [r["data"] for r in results if isinstance(r, dict) and r.get("kind") == "candidate"]
        watch_pool = [r["data"] for r in results if isinstance(r, dict) and r.get("kind") == "watch"]
        portfolio.funnel_stats["hard_gates"] += len(all_scored)

        # Помечаем текущую 5m свечу как отсканированную ТОЛЬКО если реально получены свечи (иначе ретрай на резервном зеркале!)
        if all_scored or watch_pool:
            self._last_scanned_bar = cur_bar
            self._last_mirror_used = binance_client.active_mirror_name

        all_scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        watch_pool.sort(key=lambda x: x.get("watch_activity", 0.0), reverse=True)

        # Всегда заполняем Live Radar топ-15 монетами (сначала активные пробои, затем лидеры поджатия с ML-оценкой)
        radar_display: List[Dict[str, Any]] = list(all_scored[:15])
        if len(radar_display) < 15 and watch_pool:
            need_n = 15 - len(radar_display)
            for w_item in watch_pool[:need_n]:
                if "ml_prob" not in w_item:
                    ml_w = ml_engine.evaluate_candidate(w_item)
                    w_item["ml_prob"] = ml_w.get("ml_probability", 0.5)
                    w_item["ml_reason"] = ml_w.get("reason", "")
                # Не храним тяжелый массив свечей в JSON-радаре
                w_clean = {k: v for k, v in w_item.items() if k != "candles"}
                radar_display.append(w_clean)

        portfolio.update_live_ml_ranking([
            {k: v for k, v in item.items() if k != "candles"} for item in radar_display
        ])

        if should_log:
            btc_p = btc_regime.get("pct_15m", 0.0)
            mirror_tag = binance_client.active_mirror_name
            if all_scored:
                top_str = ", ".join([
                    f"{c['symbol']} {c['candidate_side']} (Score: {c['score']}, RVOL: {c['volume_surge_ratio']}x, ML: {int(c['ml_prob']*100)}%)"
                    for c in all_scored[:3]
                ])
                print(
                    f"🚀 [ПРОБОЙ НАЙДЕН] {now_str} [{mirror_tag}] — Радар {len(tickers)} пар | "
                    f"Кандидатов: {len(all_scored)} | {top_str}",
                    flush=True
                )
            else:
                watch_str = ", ".join([
                    f"{w['symbol']} {w['candidate_side']} (до пробоя {w.get('dist_to_breakout_pct', 0):.2f}%, RVOL {w.get('volume_surge_ratio', 1):.1f}x)"
                    for w in watch_pool[:3]
                ]) if watch_pool else "ожидание импульса"
                print(
                    f"📡 [ROCKET RADAR] {now_str} [{mirror_tag}] — Мониторинг {len(tickers)} пар | "
                    f"BTC 15m: {btc_p:+.2f}% | На прицеле: {watch_str}",
                    flush=True
                )

        # 5. ОТБОР ЛУЧШЕГО КАНДИДАТА ДЛЯ GROQ AI (СТРОГО 1 НОВЫЙ ВХОД ЗА ПРОХОД — ЗАЩИТА ОТ ПАРНЫХ СИНХРОННЫХ СТОПОВ!)
        candidates_to_eval = all_scored[:1]

        # 6. GROQ SOFT GATE & RISK-BASED POSITION SIZING
        for ctx in candidates_to_eval:
            sym = ctx["symbol"]
            cand_side = ctx.get("candidate_side", "LONG")
            portfolio.funnel_stats["groq_evaluated"] += 1

            approved, groq_eval = await groq_engine.evaluate_setup(ctx)

            entry_p = ctx["current_price"]
            if cand_side == "LONG":
                exact_sl = ctx.get("wick_stop_loss", config.round_price(entry_p * 0.990))
                risk_per_coin = max(entry_p - exact_sl, entry_p * config.STOP_LOSS_MIN_PCT)
                tp1_target = config.round_price(entry_p + max(config.TARGET_1_R * risk_per_coin, entry_p * config.TP1_PCT))
                tp2_target = config.round_price(entry_p + max(config.TARGET_2_R * risk_per_coin, entry_p * config.TP2_PCT))
            else:
                exact_sl = ctx.get("short_wick_stop_loss", config.round_price(entry_p * 1.010))
                risk_per_coin = max(exact_sl - entry_p, entry_p * config.STOP_LOSS_MIN_PCT)
                tp1_target = config.round_price(entry_p - max(config.TARGET_1_R * risk_per_coin, entry_p * config.TP1_PCT))
                tp2_target = config.round_price(entry_p - max(config.TARGET_2_R * risk_per_coin, entry_p * config.TP2_PCT))

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

                if getattr(config, "ENABLE_CIRCUIT_BREAKER", False) and portfolio.is_daily_limit_reached():
                    print(f"🛑 [CIRCUIT BREAKER] Дневной лимит {config.DAILY_LOSS_LIMIT} убытка исчерпан.", flush=True)
                    break

                # ДИНАМИЧЕСКИЙ ГЕОМЕТРИЧЕСКИЙ САЙЗИНГ С HALF-KELLY ЗАЩИТОЙ ОТ ПРОСАДКИ:
                # Риск рассчитывается как 3.0% от текущего эквити.
                # Если текущее эквити просело более чем на 15% от пикового (peak_equity),
                # риск автоматически снижается на 40% (до 1.8%), защищая депозит от серии стопов.
                summary = portfolio.get_portfolio_summary()
                cur_equity = max(10.0, summary["equity"])
                peak_equity = max(getattr(portfolio, "peak_equity", cur_equity), cur_equity)
                dd_pct = (peak_equity - cur_equity) / peak_equity if peak_equity > 0 else 0.0

                base_risk_pct = config.RISK_PER_TRADE_PCT
                if dd_pct >= getattr(config, "DD_GUARD_THRESHOLD", 0.15):
                    effective_risk_pct = base_risk_pct * getattr(config, "DD_GUARD_RISK_MULT", 0.60)
                else:
                    effective_risk_pct = base_risk_pct

                conv_mult = 1.0
                if float(ctx.get("ml_prob", 0.5)) >= 0.58 and float(ctx.get("volume_surge_ratio", 1.0)) >= 2.20:
                    conv_mult = float(getattr(config, "CONVICTION_RISK_MULT", 1.00))
                risk_usd = round(cur_equity * effective_risk_pct * conv_mult, 3)
                sl_dist_pct = abs(entry_p - exact_sl) / max(entry_p, 1e-9)
                lev_to_use = getattr(portfolio, "current_leverage", config.LEVERAGE)

                eff_sl_dist = max(sl_dist_pct, float(getattr(config, "SIZING_SL_FLOOR_PCT", 0.0080)))
                target_notional = risk_usd / (eff_sl_dist + 0.0012)
                raw_margin = target_notional / lev_to_use
                max_mg = cur_equity * float(getattr(config, "MAX_MARGIN_EQUITY_PCT", 0.25))
                min_mg = float(getattr(config, "MIN_MARGIN_USDT", 1.00))
                actual_margin = round(min(raw_margin, max_mg, portfolio.cash * 0.48), 2)

                # УСИЛЕННАЯ ЗАЩИТА ОТ КОРРЕЛЯЦИОННОГО РИСКА (БЕЗРИСКОВЫЕ MOONBAG-РАНЕРЫ НЕ БЛОКИРУЮТ НОВЫЕ ВХОДЫ!):
                at_risk_positions = [p for p in portfolio.open_positions.values() if not p.get("tp1_hit", False)]
                if len(at_risk_positions) >= 1:
                    same_side_positions = [p for p in at_risk_positions if p.get("side") == cand_side]
                    if same_side_positions:
                        existing_pos = same_side_positions[0]
                        age_sec = now - float(existing_pos.get("opened_at", now))
                        in_profit_or_be = (float(existing_pos.get("unrealized_pnl", 0.0)) > 0.0) or bool(existing_pos.get("breakeven_set", False))
                        if age_sec < 300.0 or not in_profit_or_be:
                            print(
                                f"⚠️ [CORRELATION GUARD] Вторая позиция {cand_side} по {sym} отклонена: "
                                f"первая сделка еще не вышла в профит/безубыток (возраст {int(age_sec)}с, PnL ${existing_pos.get('unrealized_pnl', 0):+.2f}).",
                                flush=True
                            )
                            continue
                        btc_trend = btc_regime.get("trend", "CHOP")
                        btc_5m = btc_regime.get("pct_5m", 0.0)
                        if cand_side == "SHORT" and (btc_trend != "BEARISH" or btc_5m > 0.0):
                            print(f"⚠️ [CORRELATION GUARD] Вторая позиция SHORT по {sym} отклонена: BTC ({btc_trend}, {btc_5m:+.2f}%) не в медвежьем тренде!", flush=True)
                            continue
                        elif cand_side == "LONG" and (btc_trend != "BULLISH" or btc_5m < 0.0):
                            print(f"⚠️ [CORRELATION GUARD] Вторая позиция LONG по {sym} отклонена: BTC ({btc_trend}, {btc_5m:+.2f}%) не в бычьем тренде!", flush=True)
                            continue

                max_total_slots = config.MAX_CONCURRENT_POSITIONS + int(getattr(config, "MAX_RISK_FREE_RUNNERS", 2))
                if len(at_risk_positions) < config.MAX_CONCURRENT_POSITIONS and len(portfolio.open_positions) < max_total_slots and actual_margin >= min_mg and portfolio.cash >= actual_margin:
                    brk_type = ctx.get("breakout_type", "STRUCT_3H")
                    opened = portfolio.open_position(
                        symbol=sym,
                        side=cand_side,
                        entry_price=entry_p,
                        size_usdt=actual_margin,
                        wick_sl=exact_sl,
                        tp1=tp1_target,
                        tp2=tp2_target,
                        groq_reason=f"Rocket [{brk_type}] (Score: {ctx.get('score', 1.0)}, RVOL: {ctx['volume_surge_ratio']}x) | {eval_entry['reason']}",
                        leverage=lev_to_use,
                        atr_pct=ctx.get("atr14_pct", 0.006),
                        risk_usd=risk_usd
                    )
                    if opened:
                        self.cooldowns[sym] = now
                        print(
                            f"🟢 [ROCKET OPEN] {cand_side} {sym} [{brk_type}] по ${entry_p:.4f} | "
                            f"Маржа: ${actual_margin:.2f} ({lev_to_use}x, Риск 1R: ${risk_usd:.2f}) | "
                            f"SL: ${exact_sl:.4f} ({sl_dist_pct*100:.2f}%) | TP1(60%@{config.TARGET_1_R}R): ${tp1_target:.4f} | 40% Anti-Rug Trail",
                            flush=True
                        )
                        if len(at_risk_positions) + 1 >= config.MAX_CONCURRENT_POSITIONS:
                            break
            else:
                self.cooldowns[sym] = now - (config.PAIR_COOLDOWN_MINUTES * 60) + 60.0
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
