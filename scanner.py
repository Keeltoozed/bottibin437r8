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
    Высокоскоростной автономный сканер структурных пробоев (Alpha Rocket + Smart Money FVG).
    Выбирает индивидуальный динамический профиль TP1/TP2/Trail под каждую сделку с учетом ATR, FVG, ADX и типа пробоя!
    """
    def __init__(self):
        self.is_running = False
        self.cooldowns: Dict[str, float] = {}
        self._last_log_time = 0.0
        self._last_scanned_bar: int = 0
        self._last_mirror_used: str = ""

    @staticmethod
    def compute_dynamic_exit_plan(ctx: Dict[str, Any], side: str, sl_dist: float) -> Dict[str, Any]:
        """
        Индивидуальный ML-адаптивный план выхода:
          • TREND_PULLBACK (откат к EMA21): быстрый щит +0.85R -> БЕ+, TP1 1.00R, TP2 1.85R (WR 69–75%)
          • TOP_ROCKET (ml_prob >= TopQ35 или без ML-тега): 100% Full-Hold без раннего удушения (Lock1 1.46R / Lock2 2.25R / Trail)
          • SHIELD_WIN (средний ML [Q08..Q35]): защита +0.92R -> гарантированный плюс (перекрывает комиссии) + Full-Hold ранер!
        """
        brk_type = ctx.get("breakout_type", "STRUCT_3H")
        atr_pct = float(ctx.get("atr14_pct", 0.006) or 0.006)
        adx14 = float(ctx.get("adx14", 20.0) or 20.0)
        has_fvg = bool(ctx.get("has_fvg_bull") if side == "LONG" else ctx.get("has_fvg_bear"))
        full_hold = bool(getattr(config, "FULL_HOLD_MODE", True))
        sh1 = 0.0 if full_hold else 0.35
        sh2_rug = 0.0 if full_hold else 0.30
        sh2_std = 0.0 if full_hold else 0.25

        ml_val = ctx.get("ml_prob")
        top_thr = float(getattr(config, "ML_TOP_ROCKET_PROB", 0.495))
        med_be = float(getattr(config, "ML_MEDIUM_BE_TRIGGER_R", 0.92))
        eff_early_be = 99.0 if (ml_val is None or float(ml_val) >= top_thr) else med_be

        if brk_type == "TREND_PULLBACK":
            return {
                "profile": "TREND_PULLBACK",
                "tp1_r": 1.00, "tp1_share": sh1, "tp1_lock_r": 0.25,
                "tp2_r": 1.85, "tp2_share": sh2_std, "tp2_lock_r": 1.05,
                "trail_r": 2.60, "early_be_r": 0.85,
            }
        elif brk_type == "SM_15M":
            return {"profile": "SMART_MONEY_15M", "tp1_r": 1.15, "tp1_share": sh1, "tp1_lock_r": 0.25, "tp2_r": 1.65, "tp2_share": sh2_std, "tp2_lock_r": 0.95, "trail_r": 2.50, "early_be_r": 99.0}
        elif brk_type == "RUG_SHORT":
            return {"profile": "FAST_RUG_DUMP", "tp1_r": 1.25, "tp1_share": sh1, "tp1_lock_r": 0.25, "tp2_r": 1.95, "tp2_share": sh2_rug, "tp2_lock_r": 1.10, "trail_r": 2.80, "early_be_r": eff_early_be}
        elif brk_type == "SQUEEZE_80M" or (has_fvg and adx14 >= 20.0):
            return {"profile": "EXPLOSIVE_FVG", "tp1_r": 1.46, "tp1_share": sh1, "tp1_lock_r": 0.45, "tp2_r": 2.25, "tp2_share": sh2_std, "tp2_lock_r": 1.32, "trail_r": 3.20, "early_be_r": eff_early_be}
        elif atr_pct >= 0.012 or sl_dist >= 0.030:
            return {"profile": "HIGH_VOL_SWING", "tp1_r": 1.35, "tp1_share": sh1, "tp1_lock_r": 0.45, "tp2_r": 2.00, "tp2_share": sh2_std, "tp2_lock_r": 1.15, "trail_r": 3.20, "early_be_r": eff_early_be}
        else:
            return {"profile": "STD_TREND_FIB", "tp1_r": 1.35, "tp1_share": sh1, "tp1_lock_r": 0.45, "tp2_r": 2.25, "tp2_share": sh2_std, "tp2_lock_r": 1.32, "trail_r": 3.20, "early_be_r": eff_early_be}

    async def scan_market_once(self, force: bool = False) -> List[Dict[str, Any]]:
        """Один параллельный проход сканирования рынка строго на закрытии 5m свечи (защита от HTTP 418/429)."""
        now = time.time()
        now_str = time.strftime("%H:%M:%S")
        portfolio.last_scan_str = now_str

        # УМНАЯ ЗАЩИТА ОТ ЛИМИТОВ API (35x ЭКОНОМИЯ ВЕСА НА RENDER):
        # Стратегия работает строго по закрытым 5-минутным свечам!
        # Полный скан 80-100 пар запускается 1 раз в начале каждой новой 5m свечи (через 3с после закрытия бара),
        # а не 25 раз подряд за те же 5 минут — полностью исключает HTTP 418/429 бан на Render!
        # УМНАЯ ЗАЩИТА ОТ ЛИМИТОВ API: при самом первом старте контейнера (last_universe_count == 0) сканируем СРАЗУ (чтобы не было Радар: 0 пар!),
        # а далее ровно 1 раз после закрытия каждой новой свечи!
        scan_tf = str(getattr(config, "SCAN_TIMEFRAME", "5m")).strip() or "5m"
        bar_sec = 900 if scan_tf == "15m" else 300
        cur_bar = int(now) // bar_sec
        sec_into_bar = now % float(bar_sec)
        is_first_boot_scan = (portfolio.last_universe_count == 0 and self._last_scanned_bar == 0)
        if not force and not is_first_boot_scan and self._last_scanned_bar == cur_bar and portfolio.last_universe_count > 0:
            return []
        if not force and not is_first_boot_scan and self._last_scanned_bar > 0 and sec_into_bar < 3.0:
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

        at_risk_open = sum(1 for p in portfolio.open_positions.values() if not (p.get("tp1_hit", False) or p.get("breakeven_set", False)))
        max_total_slots = config.MAX_CONCURRENT_POSITIONS + int(getattr(config, "MAX_RISK_FREE_RUNNERS", 2))
        if at_risk_open >= config.MAX_CONCURRENT_POSITIONS or len(portfolio.open_positions) >= max_total_slots:
            return []

        # 0. MACRO GUARD: Режим Bitcoin
        btc_regime = await binance_client.fetch_btc_regime()
        portfolio.btc_regime_str = btc_regime.get("status_str", "")

        # 1. UNIVERSE: Полный мониторинг 400-500+ крипто-пар в Stage 1 -> глубокий 200-свечной разбор топ-240 активных ракет!
        tickers = await binance_client.fetch_top_tickers(
            min_vol_usdt=config.MIN_24H_VOLUME_USDT,
            limit=config.SCAN_TICKERS_LIMIT
        )
        full_market_n = max(len(tickers), getattr(binance_client, "last_full_market_count", len(tickers)))
        portfolio.last_universe_count = full_market_n
        portfolio.funnel_stats["universe"] += full_market_n

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

                # 3. Структурный свечной анализ (по умолчанию 15m Smart Money 5/7: BOS + EMA200 + MACD + ADX + FVG, 200 свечей = 50ч!)
                analysis = await binance_client.fetch_candles_analysis(sym, interval=scan_tf, limit=250)
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
                max_spike_5m = float(getattr(config, "MAX_ENTRY_5M_SPIKE_PCT", 3.50))
                min_atr_pct = float(getattr(config, "MIN_ATR_PCT", 0.0025))
                avg_5m_qvol = float(analysis.get("avg_5m_quote_vol", 0.0) or 0.0)
                v3_surge = float(analysis.get("v3_surge", 1.0) or 1.0)
                # Адаптация порога 5m объема под активное зеркало:
                # На Bitget/Bybit даже у монет с $3.5M объема (напр. JCTUSDT) и стартующих ракет (MOCAUSDT)
                # встречаются пустые минутки в стакане, поэтому отсекаем ТОЛЬКО одиночный прокол тонкой монеты
                # (когда avg_5m < $1500 И предыдущая закрытая свеча была пустой < $400, как у DOSUSDT $53!).
                is_spot_mirror = binance_client.is_spot_mirror
                m_name_now = binance_client.active_mirror_name
                is_alt_futures = m_name_now in ("bybit", "bitget", "okx", "gate")
                if is_spot_mirror:
                    min_avg_vol = float(getattr(config, "SPOT_MIRROR_MIN_AVG_5M_VOL", 600.0))
                elif is_alt_futures:
                    min_avg_vol = float(getattr(config, "ALT_FUTURES_MIN_AVG_5M_VOL", 650.0))
                else:
                    min_avg_vol = float(getattr(config, "MIN_AVG_5M_QUOTE_VOL", 3000.0))
                min_sig_vol = float(getattr(config, "MIN_SIGNAL_5M_QUOTE_VOL", 8000.0))
                alt_sig_vol = float(getattr(config, "ALT_FUTURES_MIN_SIGNAL_5M_VOL", 3500.0))
                min_bar_vol = float(getattr(config, "MIN_RECENT_5M_BAR_VOL", 400.0))
                last_5m_qvol = float(analysis.get("last_quote_volume", 0.0) or 0.0)
                prev_5m_qvol = float(analysis.get("prev_quote_volume", avg_5m_qvol) or 0.0)
                min_recent_5m_qvol = float(analysis.get("min_recent_5m_qvol", avg_5m_qvol) or 0.0)
                vol_24h_pair = float(t.get("volume_24h", 0.0) or 0.0)
                thin_single_wick_trap = (avg_5m_qvol < 1500.0 and prev_5m_qvol < min_bar_vol)
                if is_spot_mirror:
                    vol_floor_ok = (vol_24h_pair >= 750000.0) and (avg_5m_qvol >= min_avg_vol) and (last_5m_qvol >= 2000.0)
                elif is_alt_futures:
                    vol_floor_ok = (vol_24h_pair >= 1500000.0) and (avg_5m_qvol >= min_avg_vol) and (last_5m_qvol >= alt_sig_vol)
                else:
                    vol_floor_ok = (vol_24h_pair >= 1500000.0) and (avg_5m_qvol >= min_avg_vol) and (last_5m_qvol >= min_sig_vol)
                min_v3 = float(getattr(config, "MIN_V3_VOLUME_PERSISTENCE", 1.10))
                is_mtf_long = analysis.get("is_mtf_long_ok", False) if getattr(config, "ENABLE_MTF_15M_FILTER", True) else True
                is_mtf_short = analysis.get("is_mtf_short_ok", False) if getattr(config, "ENABLE_MTF_15M_FILTER", True) else True
                is_macro_long = analysis.get("is_macro_trend_long", True)
                is_macro_short = analysis.get("is_macro_trend_short", True)
                anti_rug_long = analysis.get("anti_rug_long_ok", True)
                anti_rug_short = analysis.get("anti_rug_short_ok", True)
                anti_wall_long = analysis.get("anti_wall_long_ok", True)
                anti_wall_short = analysis.get("anti_wall_short_ok", True)
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

                # Ночной фильтр низкой ликвидности (21:00–01:00 UTC — мертвое окно закрытия США до открытия Азии):
                # Не выключает радар, но требует более сильный пробойный импульс (RVOL >= 2.10x и плотный CLV >= 0.72)!
                utc_hour = time.gmtime(now).tm_hour
                is_dead_night = bool(getattr(config, "ENABLE_NIGHT_LIQUIDITY_GUARD", True)) and (utc_hour >= 21 or utc_hour < 1)
                eff_min_rvol = max(config.MIN_5M_VOLUME_SURGE_RATIO, float(getattr(config, "NIGHT_MIN_RVOL", 2.10))) if is_dead_night else config.MIN_5M_VOLUME_SURGE_RATIO
                eff_min_clv = max(config.MIN_CLOSE_STRENGTH, float(getattr(config, "NIGHT_MIN_CLOSE_STRENGTH", 0.72))) if is_dead_night else config.MIN_CLOSE_STRENGTH

                # Подтверждение институционального объема (RVOL >= 1.80x / ночью 2.10x И 3-свечной приток >= 1.10x)
                vol_confirmed = (surge >= eff_min_rvol) and (v3_surge >= min_v3)

                # ==============================================================
                # 4. ПРАВИЛА ВХОДА SMART MONEY 15M ENGINE (WR 70%, PF 2.02 НА BYBIT + 8/8 ИСТОРИЧЕСКИХ СПЛИТОВ!)
                # - На 15m: 5/7 Smart Money Confluence (4ч BOS + HTF EMA200 + MACD + ADX>=20 + FVG/RVOL + Alpha к BTC >= 0.45%)
                # - Строгое выравнивание по макро-режиму Bitcoin (LONG выше EMA50 BTC, SHORT ниже EMA50 BTC)
                # - Узкий структурный стоп <= 2.20% (полная защита от дыр по -150%..-189%)
                # ==============================================================
                if scan_tf == "15m":
                    vol_15m_ok = (vol_24h_pair >= (250000.0 if is_spot_mirror else 500000.0)) and (avg_5m_qvol >= (1200.0 if is_spot_mirror else 2500.0))
                    btc_bull_ok = bool(btc_regime.get("btc_macro_bull", True)) if getattr(config, "ENABLE_BTC_MACRO_ALIGNMENT", True) else not btc_regime.get("is_dumping", False)
                    btc_bear_ok = bool(btc_regime.get("btc_macro_bear", True)) if getattr(config, "ENABLE_BTC_MACRO_ALIGNMENT", True) else not btc_regime.get("is_pumping", False)
                    tech_long = (
                        analysis.get("sm15_long", False) and
                        vol_15m_ok and
                        pct_5m <= 5.50 and
                        alpha_5m >= 0.45 and
                        analysis.get("live_drift_long_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT and
                        not analysis.get("breakout_failed_long", False) and
                        config.STOP_LOSS_MIN_PCT <= sl_long_dist <= config.STOP_LOSS_MAX_PCT
                    )
                    is_long = tech_long and btc_bull_ok and not btc_regime.get("is_spike_up", False)

                    tech_short = (
                        config.ENABLE_SHORT and
                        analysis.get("sm15_short", False) and
                        vol_15m_ok and
                        pct_5m >= -5.50 and
                        alpha_5m <= -0.45 and
                        analysis.get("live_drift_short_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT and
                        not analysis.get("breakout_failed_short", False) and
                        config.STOP_LOSS_MIN_PCT <= sl_short_dist <= config.STOP_LOSS_MAX_PCT
                    )
                    is_short = tech_short and btc_bear_ok and not btc_regime.get("is_flush_down", False)
                    is_sm_fvg = False
                    if is_long or is_short:
                        brk_type = "SM_15M"
                        analysis["breakout_type"] = "SM_15M"
                else:
                    btc_bull_5m = bool(btc_regime.get("btc_macro_bull", True)) if getattr(config, "ENABLE_BTC_MACRO_ALIGNMENT", True) else True
                    btc_bear_5m = bool(btc_regime.get("btc_macro_bear", True)) if getattr(config, "ENABLE_BTC_MACRO_ALIGNMENT", True) else True
                    tech_long = (
                        analysis.get("is_breakout_long", False) and
                        anti_rug_long and
                        anti_wall_long and
                        atr_pct >= min_atr_pct and
                        vol_confirmed and
                        vol_floor_ok and
                        is_mtf_long and
                        is_macro_long and
                        min_req_impulse <= pct_5m <= max_spike_5m and
                        alpha_5m >= min_a5 and
                        alpha_15m >= min_a15 and
                        clv_long >= eff_min_clv and
                        upper_wick <= config.WICK_EXHAUSTION_MAX and
                        sig_close > ema9 and ema9 >= ema21 * 0.998 and
                        config.MIN_RSI_LONG <= rsi <= config.MAX_RSI_LONG and
                        ema21_ext <= config.MAX_EMA21_EXTENSION_PCT and
                        analysis.get("live_drift_long_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT and
                        not analysis.get("breakout_failed_long", False) and
                        config.STOP_LOSS_MIN_PCT <= sl_long_dist <= config.STOP_LOSS_MAX_PCT
                    )
                    indep_long_ok = (surge >= 2.80 and alpha_5m >= 1.50)
                    indep_short_ok = (surge >= 2.80 and alpha_5m <= -1.50)
                    eff_btc_l = btc_bull_5m or indep_long_ok
                    eff_btc_s = btc_bear_5m or indep_short_ok
                    is_long = tech_long and eff_btc_l and not btc_regime.get("is_dumping", False) and not btc_regime.get("is_spike_up", False)

                    tech_short = (
                        config.ENABLE_SHORT and
                        analysis.get("is_breakout_short", False) and
                        anti_rug_short and
                        anti_wall_short and
                        atr_pct >= min_atr_pct and
                        vol_confirmed and
                        vol_floor_ok and
                        is_mtf_short and
                        is_macro_short and
                        -max_spike_5m <= pct_5m <= -min_req_impulse and
                        alpha_5m <= -min_a5 and
                        alpha_15m <= -min_a15 and
                        clv_short >= eff_min_clv and
                        lower_wick <= config.WICK_EXHAUSTION_MAX and
                        sig_close < ema9 and ema9 <= ema21 * 1.002 and
                        config.MIN_RSI_SHORT <= rsi <= config.MAX_RSI_SHORT and
                        ema21_ext <= config.MAX_EMA21_EXTENSION_PCT and
                        analysis.get("live_drift_short_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT and
                        not analysis.get("breakout_failed_short", False) and
                        config.STOP_LOSS_MIN_PCT <= sl_short_dist <= config.STOP_LOSS_MAX_PCT
                    )
                    is_short = tech_short and (eff_btc_s or brk_type == "RUG_SHORT") and not btc_regime.get("is_pumping", False) and not btc_regime.get("is_flush_down", False)

                    # SMART MONEY FVG + BOS + MACD + ADX >= 20 (включая ранние V-развороты 3/7 со дна ниже EMA200, как #MON!)
                    is_sm_fvg = False
                    if (not is_long and not is_short) and getattr(config, "ENABLE_SM_FVG_ENTRY", True):
                        adx14_val = float(analysis.get("adx14", 0.0) or 0.0)
                        sm_long_sl = float(analysis.get("sm_long_sl_pct", sl_long_dist) or sl_long_dist)
                        sm_short_sl = float(analysis.get("sm_short_sl_pct", sl_short_dist) or sl_short_dist)
                        sm_min_rv = eff_min_rvol if is_dead_night else 1.50
                        ema63_val = float(analysis.get("ema63", sig_close) or sig_close)
                        sm_htf_l = is_mtf_long or (sig_close >= ema63_val * 0.998 and bool(analysis.get("macd_bull", False)))
                        sm_htf_s = is_mtf_short or (sig_close <= ema63_val * 1.002 and bool(analysis.get("macd_bear", False)))
                        sm_tech_l = (
                            analysis.get("sm_bos_long", False) and
                            anti_wall_long and surge >= sm_min_rv and
                            vol_floor_ok and atr_pct >= min_atr_pct and v3_surge >= min_v3 and
                            adx14_val >= 20.0 and sm_htf_l and ema21_ext <= 0.032 and
                            alpha_5m >= 0.65 and alpha_15m >= 0.90 and
                            clv_long >= 0.70 and upper_wick <= 0.24 and
                            50.0 <= rsi <= 78.0 and pct_5m <= max_spike_5m and analysis.get("live_drift_long_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT and
                            config.STOP_LOSS_MIN_PCT <= sm_long_sl <= config.STOP_LOSS_MAX_PCT
                        )
                        if sm_tech_l and eff_btc_l and not btc_regime.get("is_dumping", False) and not btc_regime.get("is_spike_up", False):
                            is_long = True
                            is_sm_fvg = True
                            brk_type = "SM_FVG"
                            sl_long_dist = sm_long_sl
                            analysis["breakout_type"] = "SM_FVG"
                            analysis["sl_pct_distance"] = sm_long_sl
                            analysis["wick_stop_loss"] = analysis.get("sm_long_wick_sl", analysis["wick_stop_loss"])
                        elif config.ENABLE_SHORT:
                            sm_tech_s = (
                                analysis.get("sm_bos_short", False) and
                                anti_wall_short and surge >= sm_min_rv and
                                vol_floor_ok and atr_pct >= min_atr_pct and v3_surge >= min_v3 and
                                adx14_val >= 20.0 and sm_htf_s and ema21_ext <= 0.032 and
                                alpha_5m <= -0.65 and alpha_15m <= -0.90 and
                                clv_short >= 0.70 and lower_wick <= 0.24 and
                                22.0 <= rsi <= 50.0 and pct_5m >= -max_spike_5m and analysis.get("live_drift_short_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT and
                                config.STOP_LOSS_MIN_PCT <= sm_short_sl <= config.STOP_LOSS_MAX_PCT
                            )
                            if sm_tech_s and eff_btc_s and not btc_regime.get("is_pumping", False) and not btc_regime.get("is_flush_down", False):
                                is_short = True
                                is_sm_fvg = True
                                brk_type = "SM_FVG"
                                sl_short_dist = sm_short_sl
                                analysis["breakout_type"] = "SM_FVG"
                                analysis["short_sl_dist"] = sm_short_sl
                                analysis["short_sl_pct_distance"] = sm_short_sl
                                analysis["short_wick_stop_loss"] = analysis.get("sm_short_wick_sl", analysis["short_wick_stop_loss"])
                                analysis["short_wick_sl"] = analysis["short_wick_stop_loss"]

                    # СНАЙПЕР ТРЕНДОВОГО ОТКАТА К EMA21 (WR 69–75% в свободные слоты <= PULLBACK_MAX_SLOTS!):
                    pb_max_slots = int(getattr(config, "PULLBACK_MAX_SLOTS", 8))
                    if (
                        (not is_long and not is_short)
                        and getattr(config, "ENABLE_TREND_PULLBACK", True)
                        and at_risk_open < pb_max_slots
                        and not is_dead_night
                        and vol_floor_ok
                        and atr_pct >= min_atr_pct
                    ):
                        pb_sl_l = float(analysis.get("pb_long_sl_pct", 0.99) or 0.99)
                        pb_sl_s = float(analysis.get("pb_short_sl_pct", 0.99) or 0.99)
                        if (
                            analysis.get("is_pullback_long", False)
                            and btc_bull_5m
                            and not btc_regime.get("is_dumping", False)
                            and alpha_5m >= 0.35
                            and analysis.get("live_drift_long_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT
                            and config.STOP_LOSS_MIN_PCT <= pb_sl_l <= 0.0280
                        ):
                            is_long = True
                            brk_type = "TREND_PULLBACK"
                            sl_long_dist = pb_sl_l
                            analysis["breakout_type"] = "TREND_PULLBACK"
                            analysis["sl_pct_distance"] = pb_sl_l
                            analysis["wick_stop_loss"] = analysis.get("pb_long_wick_sl", analysis["wick_stop_loss"])
                        elif (
                            config.ENABLE_SHORT
                            and analysis.get("is_pullback_short", False)
                            and btc_bear_5m
                            and not btc_regime.get("is_pumping", False)
                            and alpha_5m <= -0.35
                            and analysis.get("live_drift_short_pct", 0.0) <= config.MAX_LIVE_DRIFT_PCT
                            and config.STOP_LOSS_MIN_PCT <= pb_sl_s <= 0.0280
                        ):
                            is_short = True
                            brk_type = "TREND_PULLBACK"
                            sl_short_dist = pb_sl_s
                            analysis["breakout_type"] = "TREND_PULLBACK"
                            analysis["short_sl_dist"] = pb_sl_s
                            analysis["short_sl_pct_distance"] = pb_sl_s
                            analysis["short_wick_stop_loss"] = analysis.get("pb_short_wick_sl", analysis["short_wick_stop_loss"])
                            analysis["short_wick_sl"] = analysis["short_wick_stop_loss"]

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
                        elif (watch_side == "LONG" and not anti_wall_long) or (watch_side == "SHORT" and not anti_wall_short):
                            w_status = "🧱 Стена 12ч Double-Top/Дна (отсев 2-го круга)"
                        elif thin_single_wick_trap:
                            w_status = f"🕳️ Одиночный прокол пустого стакана (пред. 5m ${prev_5m_qvol:.0f})"
                        elif avg_5m_qvol < min_avg_vol:
                            w_status = f"💤 Тонкая монета (${avg_5m_qvol:.0f} < ${min_avg_vol:.0f})"
                        elif surge < eff_min_rvol:
                            w_status = f"📊 Пробой есть, ждем RVOL ({surge:.1f}x < {eff_min_rvol:.1f}x)"
                        elif v3_surge < min_v3:
                            w_status = f"📊 Одиночный всплеск (RVOL 3b: {v3_surge:.2f}x < {min_v3:.2f}x)"
                        elif abs(pct_5m) > max_spike_5m:
                            w_status = f"🌋 Выдохшийся спайк 5m ({pct_5m:+.2f}% > {max_spike_5m:.1f}%)"
                        elif abs(pct_5m) < min_req_impulse:
                            w_status = f"⚡ Слабый импульс ({pct_5m:+.2f}% < {min_req_impulse:.2f}%)"
                        elif clv_w < eff_min_clv or wick_w > config.WICK_EXHAUSTION_MAX:
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

                # Оценка квантовой моделью строго по закрытой сигнальной свече (Dual Multi-Scale 5m+15m)
                ml_res = ml_engine.evaluate_candidate(chosen)
                chosen["ml_prob"] = ml_res.get("ml_probability", 0.5)
                chosen["ml_reason"] = ml_res.get("reason", "")
                chosen["ml_approved"] = ml_res.get("ml_approved", False)
                chosen["ml_tier"] = ml_res.get("ml_tier", "TOP_ROCKET")

                min_ml = float(getattr(config, "ML_PULLBACK_MIN_PROB", 0.484)) if brk_type == "TREND_PULLBACK" else float(getattr(config, "ML_MIN_FILTER_PROB", 0.450))
                if min_ml > 0 and ml_res.get("ml_active") and chosen["ml_prob"] < min_ml:
                    portfolio.funnel_stats["gate_failed"] = portfolio.funnel_stats.get("gate_failed", 0) + 1
                    chosen["radar_status"] = f"🧠 Отсев ML [{brk_type}] ({chosen['ml_prob']*100:.1f}% < {min_ml*100:.1f}%)"
                    chosen["watch_activity"] = round(surge * 3.0 + abs(alpha_5m), 3)
                    return {"kind": "watch", "data": chosen}

                # Приоритет + ML-взвешивание: топ-вероятностные ракеты поднимаются выше, откаты добирают свободные слоты
                ml_mult = (max(chosen["ml_prob"], 0.25) / 0.50) ** 1.5
                if brk_type == "TREND_PULLBACK":
                    chosen["score"] = round(0.75 * surge * clv_used * ml_mult, 3)
                    chosen["radar_status"] = f"🎯 ОТКАТ К EMA21 [{chosen['ml_tier']}] (ML {chosen['ml_prob']*100:.1f}%)"
                else:
                    sm_mult = 0.85 if is_sm_fvg else 1.0
                    if not is_sm_fvg:
                        if (side == "LONG" and analysis.get("has_fvg_bull") and analysis.get("above_ema200")) or (
                            side == "SHORT" and analysis.get("has_fvg_bear") and not analysis.get("above_ema200", True)
                        ):
                            sm_mult *= float(getattr(config, "FVG_EMA200_SCORE_BOOST", 1.25))
                        if float(analysis.get("adx14", 0.0) or 0.0) >= 20.0:
                            sm_mult *= float(getattr(config, "ADX_TREND_SCORE_BOOST", 1.15))

                    chosen["score"] = round(abs(alpha_5m) * surge * clv_used * sm_mult * ml_mult, 3)
                    chosen["radar_status"] = f"🚀 ALPHA ПРОБОЙ [{brk_type} | {chosen['ml_tier']}] (RS {alpha_5m:+.1f}%)"
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
                    f"🚀 [ПРОБОЙ НАЙДЕН] {now_str} [{mirror_tag}] — Радар {portfolio.last_universe_count} пар (разбор {len(tickers)}) | "
                    f"Кандидатов: {len(all_scored)} | {top_str}",
                    flush=True
                )
            else:
                watch_str = ", ".join([
                    f"{w['symbol']} {w['candidate_side']} (до пробоя {w.get('dist_to_breakout_pct', 0):.2f}%, RVOL {w.get('volume_surge_ratio', 1):.1f}x)"
                    for w in watch_pool[:3]
                ]) if watch_pool else "ожидание импульса"
                print(
                    f"📡 [ROCKET RADAR] {now_str} [{mirror_tag}] — Мониторинг {portfolio.last_universe_count} пар (глубокий разбор {len(tickers)}) | "
                    f"BTC 15m: {btc_p:+.2f}% | На прицеле: {watch_str}",
                    flush=True
                )

        # 5. ОТБОР ВСЕХ АКТИВНЫХ СИГНАЛОВ ЗА ПРОХОД (до 10 за один 5m бар, заполняя все 15 слотов!)
        candidates_to_eval = all_scored[:10]

        # 6. GROQ ANALYTICS & ENTER-ALL EXECUTION ("Заходим в КАЖДЫЙ сигнал формулы, включая ранние 3/7 ракеты!")
        for ctx in candidates_to_eval:
            sym = ctx["symbol"]
            cand_side = ctx.get("candidate_side", "LONG")
            portfolio.funnel_stats["groq_evaluated"] += 1

            approved, groq_eval = await groq_engine.evaluate_setup(ctx)
            if not approved and getattr(config, "ENTER_ALL_QUANT_SIGNALS", True):
                approved = True
                expected_dec = "BUY" if cand_side == "LONG" else "SHORT"
                groq_eval["decision"] = expected_dec
                groq_eval["confidence"] = max(float(groq_eval.get("confidence", 0.0) or 0.0), 0.72)
                raw_rsn = str(groq_eval.get("reason") or "").strip()
                groq_eval["reason"] = f"[Auto-Enter All Signals] {raw_rsn}" if raw_rsn else "Авто-вход по формуле Smart Money / Rocket (все сигналы в работе)"

            entry_p = ctx["current_price"]
            sl_dist_pct_dyn = ctx.get("sl_pct_distance", 0.01) if cand_side == "LONG" else ctx.get("short_sl_dist", 0.01)
            exit_plan = self.compute_dynamic_exit_plan(ctx, cand_side, float(sl_dist_pct_dyn or 0.01))
            if cand_side == "LONG":
                exact_sl = ctx.get("wick_stop_loss", config.round_price(entry_p * 0.990))
                risk_per_coin = max(entry_p - exact_sl, entry_p * config.STOP_LOSS_MIN_PCT)
                tp1_target = config.round_price(entry_p + exit_plan["tp1_r"] * risk_per_coin)
                tp2_target = config.round_price(entry_p + exit_plan["tp2_r"] * risk_per_coin)
            else:
                exact_sl = ctx.get("short_wick_stop_loss", config.round_price(entry_p * 1.010))
                risk_per_coin = max(exact_sl - entry_p, entry_p * config.STOP_LOSS_MIN_PCT)
                tp1_target = config.round_price(entry_p - exit_plan["tp1_r"] * risk_per_coin)
                tp2_target = config.round_price(entry_p - exit_plan["tp2_r"] * risk_per_coin)

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

                # ЕДИНЫЙ САЙЗИНГ ПОРТФЕЛЯ:
                # 1. equal_margin ("как они"): каждая сделка открывается НА ОДИНАКОВУЮ МАРЖУ (3.5% от эквити = $3.50 / $175 @ 50x при $100),
                #    без перекосов $2.81 vs $5.19 между монетами. Опорный баланс (cash + locked) не прыгает от микро-тиков открытых позиций!
                # 2. risk_parity: переменная маржа под фиксированный долларовый риск на сделку.
                summary = portfolio.get_portfolio_summary()
                cur_equity = max(10.0, summary["equity"])
                ref_equity = max(10.0, portfolio.cash + sum(float(p.get("margin_usdt", 0.0) or 0.0) for p in portfolio.open_positions.values()))
                peak_equity = max(getattr(portfolio, "peak_equity", cur_equity), cur_equity)
                dd_pct = (peak_equity - cur_equity) / peak_equity if peak_equity > 0 else 0.0
                dd_mult = float(getattr(config, "DD_GUARD_RISK_MULT", 0.75)) if dd_pct >= getattr(config, "DD_GUARD_THRESHOLD", 0.20) else 1.0

                conv_mult = 1.0
                if float(ctx.get("ml_prob", 0.5)) >= 0.58 and float(ctx.get("volume_surge_ratio", 1.0)) >= 2.20:
                    conv_mult = float(getattr(config, "CONVICTION_RISK_MULT", 1.00))

                sl_dist_pct = abs(entry_p - exact_sl) / max(entry_p, 1e-9)
                lev_to_use = getattr(portfolio, "current_leverage", config.LEVERAGE)
                eff_sl_dist = max(sl_dist_pct, float(getattr(config, "SIZING_SL_FLOOR_PCT", 0.0080)))
                max_mg = ref_equity * float(getattr(config, "MAX_MARGIN_EQUITY_PCT", 0.30))
                min_mg = float(getattr(config, "MIN_MARGIN_USDT", 0.50))

                sizing_mode = str(getattr(config, "SIZING_MODE", "equal_margin")).lower()
                if sizing_mode == "equal_margin":
                    fixed_mg_pct = float(getattr(config, "FIXED_MARGIN_PCT", 0.025))
                    max_risk_pct = float(getattr(config, "MAX_RISK_PER_TRADE_PCT", 0.028))
                    raw_margin = ref_equity * fixed_mg_pct * dd_mult * conv_mult
                    # Жесткий потолок долларового убытка на стопе (исключает дыры по -$6..-$7 / -189% на волатильных свечах!)
                    max_mg_by_risk = (ref_equity * max_risk_pct * dd_mult) / max((eff_sl_dist + 0.0012) * lev_to_use, 1e-6)
                    actual_margin = round(min(raw_margin, max_mg_by_risk, max_mg, portfolio.cash * 0.50), 2)
                    risk_usd = round(max(actual_margin * lev_to_use * eff_sl_dist, 0.25), 3)
                else:
                    effective_risk_pct = config.RISK_PER_TRADE_PCT * dd_mult
                    risk_usd = round(cur_equity * effective_risk_pct * conv_mult, 3)
                    target_notional = risk_usd / (eff_sl_dist + 0.0012)
                    raw_margin = target_notional / lev_to_use
                    actual_margin = round(min(raw_margin, max_mg, portfolio.cash * 0.50), 2)

                # CORRELATION & DIRECTIONAL BETA GUARD (ДО 15 АКТИВНЫХ СЛОТОВ + ЗАЩИТА ОТ СНОСА ПАЧКИ НА BTC!):
                # 1. Безрисковые ранеры (tp1_hit=True или breakeven_set=True после ML Shield) НЕ занимают 15 активных слотов!
                # 2. Снайперские откаты TREND_PULLBACK занимают только до PULLBACK_MAX_SLOTS (8) слотов, резервируя место под взрывные ракеты.
                at_risk_positions = [p for p in portfolio.open_positions.values() if not (p.get("tp1_hit", False) or p.get("breakeven_set", False))]
                brk_type_chk = ctx.get("breakout_type", "STRUCT_3H")
                if brk_type_chk == "TREND_PULLBACK" and len(at_risk_positions) >= int(getattr(config, "PULLBACK_MAX_SLOTS", 8)):
                    continue
                if len(at_risk_positions) >= 1:
                    same_side_positions = [p for p in at_risk_positions if p.get("side") == cand_side]
                    max_same_side = int(getattr(config, "MAX_SAME_SIDE_POSITIONS", 6))
                    if len(same_side_positions) >= max_same_side:
                        print(f"⚠️ [DIRECTIONAL CAP] Доп. {cand_side} по {sym} пропущен: уже {len(same_side_positions)}/{max_same_side} в одну сторону!", flush=True)
                        continue
                    if same_side_positions:
                        btc_5m = float(btc_regime.get("pct_5m", 0.0) or 0.0)
                        btc_15m = float(btc_regime.get("pct_15m", 0.0) or 0.0)
                        if cand_side == "SHORT" and (btc_15m >= 0.40 or btc_5m >= 0.30):
                            print(f"⚠️ [CORRELATION GUARD] Доп. SHORT по {sym} отклонен: BTC растет ({btc_5m:+.2f}% / 15m {btc_15m:+.2f}%)!", flush=True)
                            continue
                        elif cand_side == "LONG" and (btc_15m <= -0.40 or btc_5m <= -0.30):
                            print(f"⚠️ [CORRELATION GUARD] Доп. LONG по {sym} отклонен: BTC снижается ({btc_5m:+.2f}% / 15m {btc_15m:+.2f}%)!", flush=True)
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
                        groq_reason=f"Rocket [{brk_type} | {exit_plan['profile']}] (Score: {ctx.get('score', 1.0)}, RVOL: {ctx['volume_surge_ratio']}x) | {eval_entry['reason']}",
                        leverage=lev_to_use,
                        atr_pct=ctx.get("atr14_pct", 0.006),
                        risk_usd=risk_usd,
                        exit_plan=exit_plan
                    )
                    if opened:
                        self.cooldowns[sym] = now
                        trail_left = int(round((1.0 - exit_plan["tp1_share"] - exit_plan["tp2_share"]) * 100))
                        if exit_plan["tp1_share"] <= 0.001:
                            sh_info = f"Shield(+@{exit_plan['early_be_r']:.2f}R) | " if float(exit_plan.get("early_be_r", 99.0)) < 90.0 else ""
                            tp_info = f"{sh_info}Lock1(БУ+@{exit_plan['tp1_r']}R): {config.round_price(tp1_target)} | Lock2(+{exit_plan['tp2_lock_r']}R@{exit_plan['tp2_r']}R): {config.round_price(tp2_target)} | 100% Full-Hold Trail"
                        else:
                            tp_info = f"TP1({int(exit_plan['tp1_share']*100)}%@{exit_plan['tp1_r']}R): {config.round_price(tp1_target)} | TP2({int(exit_plan['tp2_share']*100)}%@{exit_plan['tp2_r']}R): {config.round_price(tp2_target)} | {trail_left}% Trail"
                        print(
                            f"🟢 [ROCKET OPEN] {cand_side} {sym} [{brk_type} | {exit_plan['profile']} | ML {ctx.get('ml_prob', 0.5)*100:.1f}%] по {config.round_price(entry_p)} | "
                            f"Маржа: ${actual_margin:.2f} ({lev_to_use}x, Риск 1R: ${risk_usd:.2f}) | "
                            f"SL: {config.round_price(exact_sl)} ({sl_dist_pct*100:.2f}%) | {tp_info}",
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
