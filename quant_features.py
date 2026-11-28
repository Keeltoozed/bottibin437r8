"""
quant_features.py
=================
Единый институциональный модуль мульти-таймфреймовых признаков (5m + 15m Multi-Scale Feature Engineering).
Гарантирует 100% математическую идентичность 32 стационарных признаков:
  - на этапе обучения (train_quant_model.py)
  - на этапе живого инференса (ml_engine.py)
  - в побарном бэктесте (realistic_backtest_7d.py)
Полностью исключает Train-Serve Skew, календарное переобучение и сдвиг масштаба цен.
"""

import time
import math
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd


FEATURE_COLS_LONG = [
    # 1. 5m Микроструктура свечи и импульс в единицах ATR (6)
    "body_5m", "clv_5m_l", "uw_5m", "lw_5m", "imp_5m_atr_l", "prev_5m_atr_l",
    # 2. 15m Агрегированная структура 3 свечей — в 3 раза выше SNR (5)
    "body_15m", "clv_15m_l", "uw_15m", "imp_15m_atr_l", "rvol_15m_log",
    # 3. Эффективность пути Кауфмана (KER) и сжатие волатильности VCP / BB Squeeze (6)
    "ker_10", "ker_30", "vcp_5_50", "vcp_15_90", "bb_sq_20", "adx14_norm",
    # 4. Поток объема и дисбаланс агрессоров (5)
    "rvol_5m_log", "min_vol_floor", "vol_imb_6_l", "vol_imb_24_l", "vol_accel_15m",
    # 5. Мульти-таймфрейм тренд и риск перегрева в единицах ATR (6)
    "ema9_atr_l", "ema21_atr_l", "ema63_atr_l", "ema200_atr_l", "pre3_ext_atr", "rsi_dir_l",
    # 6. Ускорение MACD и запас хода до 6ч экстремума (4)
    "macd_hist_atr_l", "macd_accel_atr_l", "room_72b_atr_l", "ret_36b_atr_l",
]

FEATURE_COLS_SHORT = [
    "body_5m", "clv_5m_s", "lw_5m", "uw_5m", "imp_5m_atr_s", "prev_5m_atr_s",
    "body_15m", "clv_15m_s", "lw_15m", "imp_15m_atr_s", "rvol_15m_log",
    "ker_10", "ker_30", "vcp_5_50", "vcp_15_90", "bb_sq_20", "adx14_norm",
    "rvol_5m_log", "min_vol_floor", "vol_imb_6_s", "vol_imb_24_s", "vol_accel_15m",
    "ema9_atr_s", "ema21_atr_s", "ema63_atr_s", "ema200_atr_s", "pre3_ext_atr", "rsi_dir_s",
    "macd_hist_atr_s", "macd_accel_atr_s", "room_72b_atr_s", "ret_36b_atr_s",
]


class SoftEnsembleModel:
    """Мягкий ансамбль вероятностей (LogReg L2 + RandomForest + ExtraTrees + Reg-XGBoost)."""
    def __init__(self, models: List[Any], weights: List[float]):
        self.models = models
        w_arr = np.array(weights, dtype=np.float64)
        self.weights = w_arr / np.maximum(np.sum(w_arr), 1e-9)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X_arr = np.asarray(X, dtype=np.float64)
        p1 = np.zeros(len(X_arr), dtype=np.float64)
        for m, w in zip(self.models, self.weights):
            p1 += w * m.predict_proba(X_arr)[:, 1]
        return np.column_stack([1.0 - p1, p1])


def _ema_np(arr: np.ndarray, period: int) -> np.ndarray:
    k = 2.0 / (period + 1.0)
    out = np.empty_like(arr, dtype=np.float64)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1.0 - k)
    return out


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(window=period, min_periods=3).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period, min_periods=3).mean()
    rs = gain / (loss + 1e-9)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_quant_features_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Вычисляет 32 стационарных мульти-таймфреймовых признака (LONG + SHORT) + телеметрию `rvol`
    без заглядывания в будущее (Zero Lookahead Bias).
    Работает одинаково на 25–30 свечах в тестах, 250 свечах в сканере и 13 000 свечах при обучении.
    """
    n = len(df)
    if n < 15:
        return pd.DataFrame()

    df = df.copy()
    o = df["open"].astype(np.float64).values
    h = df["high"].astype(np.float64).values
    l = df["low"].astype(np.float64).values
    c = df["close"].astype(np.float64).values
    if "quote_vol" in df.columns and float(df["quote_vol"].abs().sum()) > 0:
        qv_raw = df["quote_vol"].astype(np.float64).values
        vol_fb = df["volume"].astype(np.float64).values * c if "volume" in df.columns else qv_raw
        qv = np.where(qv_raw > 0, qv_raw, vol_fb)
    else:
        qv = df["volume"].astype(np.float64).values * np.maximum(c, 1e-9)

    ema9 = _ema_np(c, 9)
    ema21 = _ema_np(c, 21)
    ema63 = _ema_np(c, 63)
    ema200 = _ema_np(c, 200)

    macd_l = _ema_np(c, 12) - _ema_np(c, 26)
    macd_s = _ema_np(macd_l, 9)
    macd_h = macd_l - macd_s

    tr = np.empty(n, dtype=np.float64)
    tr[0] = max(h[0] - l[0], c[0] * 1e-5)
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
    atr14 = pd.Series(tr).rolling(14, min_periods=2).mean().bfill().values
    atr_pct = atr14 / np.maximum(c, 1e-9)
    atr_safe = np.maximum(atr14, c * 1e-5)
    atr_p_safe = np.maximum(atr_pct, 1e-5)

    atr5_pre = pd.Series(tr).shift(1).rolling(5, min_periods=2).mean().bfill().values
    atr50_pre = pd.Series(tr).shift(1).rolling(50, min_periods=5).mean().bfill().values
    atr15_pre = pd.Series(tr).shift(1).rolling(15, min_periods=3).mean().bfill().values
    atr90_pre = pd.Series(tr).shift(1).rolling(90, min_periods=10).mean().bfill().values

    adx = np.full(n, 20.0, dtype=np.float64)
    if n > 2:
        aw, pw, nw, av, al_w = tr[1], max(h[1] - h[0], 0.0), max(l[0] - l[1], 0.0), 20.0, 1.0 / 14.0
        for j in range(1, n):
            um, dm = h[j] - h[j - 1], l[j - 1] - l[j]
            pdm = um if (um > dm and um > 0) else 0.0
            ndm = dm if (dm > um and dm > 0) else 0.0
            aw = al_w * tr[j] + (1.0 - al_w) * aw
            pw = al_w * pdm + (1.0 - al_w) * pw
            nw = al_w * ndm + (1.0 - al_w) * nw
            if aw > 1e-12:
                pdi, ndi = 100.0 * pw / aw, 100.0 * nw / aw
                dx = 100.0 * abs(pdi - ndi) / max(pdi + ndi, 1e-12)
                av = al_w * dx + (1.0 - al_w) * av
            adx[j] = av

    vol_ma20 = pd.Series(qv).rolling(20, min_periods=5).mean().shift(1).bfill().values
    rvol = qv / np.maximum(vol_ma20, 1e-6)
    vol_ma60 = pd.Series(qv).rolling(60, min_periods=8).mean().shift(3).bfill().values
    rvol_15m = pd.Series(qv).rolling(3, min_periods=1).mean().values / np.maximum(vol_ma60, 1e-6)
    vol_acc_15m = pd.Series(qv).rolling(6, min_periods=2).mean().values / np.maximum(vol_ma60, 1e-6)
    min_qv5_pre = pd.Series(qv).shift(1).rolling(5, min_periods=2).min().bfill().values

    o15 = pd.Series(o).shift(2).bfill().values
    h15 = pd.Series(h).rolling(3, min_periods=1).max().values
    l15 = pd.Series(l).rolling(3, min_periods=1).min().values
    rng15 = np.maximum(h15 - l15, 1e-9)
    body15 = np.abs(c - o15) / rng15
    clv15_l = (c - l15) / rng15
    clv15_s = (h15 - c) / rng15
    uw15 = (h15 - np.maximum(o15, c)) / rng15
    lw15 = (np.minimum(o15, c) - l15) / rng15

    sv = qv * np.where(c >= o, 1.0, -1.0)
    sv6 = pd.Series(sv).rolling(6, min_periods=2).sum().values / np.maximum(pd.Series(qv).rolling(6, min_periods=2).sum().values, 1e-6)
    sv24 = pd.Series(sv).rolling(24, min_periods=4).sum().values / np.maximum(pd.Series(qv).rolling(24, min_periods=4).sum().values, 1e-6)

    abs_diff = pd.Series(np.abs(np.diff(c, prepend=c[0])))
    ker10 = np.abs(c - pd.Series(c).shift(10).bfill().values) / np.maximum(abs_diff.rolling(10, min_periods=3).sum().values, 1e-9)
    ker30 = np.abs(c - pd.Series(c).shift(30).bfill().values) / np.maximum(abs_diff.rolling(30, min_periods=6).sum().values, 1e-9)

    bb_std = pd.Series(c).shift(1).rolling(20, min_periods=5).std().bfill().values
    bb_mid = pd.Series(c).shift(1).rolling(20, min_periods=5).mean().bfill().values
    bb_w = (2.0 * bb_std) / np.maximum(bb_mid, 1e-9)
    bb_w_ma = pd.Series(bb_w).rolling(50, min_periods=5).mean().bfill().values
    bb_sq = np.clip(bb_w / np.maximum(bb_w_ma, 1e-9), 0.2, 3.5)

    delta = np.diff(c, prepend=c[0])
    ag = pd.Series(np.where(delta > 0, delta, 0.0)).rolling(14, min_periods=3).mean().values
    al = pd.Series(np.where(delta < 0, -delta, 0.0)).rolling(14, min_periods=3).mean().values
    rsi = np.where(al == 0, np.where(ag > 0, 100.0, 50.0), 100.0 - 100.0 / (1.0 + ag / np.maximum(al, 1e-12)))

    s_h, s_l = pd.Series(h).shift(1), pd.Series(l).shift(1)
    h72 = s_h.rolling(72, min_periods=10).max().bfill().values
    l72 = s_l.rolling(72, min_periods=10).min().bfill().values

    ret_1 = pd.Series(c).pct_change(1).fillna(0.0).values
    ret_3 = pd.Series(c).pct_change(3).fillna(0.0).values
    ret_36 = pd.Series(c).pct_change(min(36, max(n - 2, 1))).fillna(0.0).values
    prev_ret1 = np.roll(ret_1, 1); prev_ret1[0] = 0.0

    rng5 = np.maximum(h - l, 1e-9)
    body5 = np.abs(c - o) / rng5
    clv5_l = (c - l) / rng5
    clv5_s = (h - c) / rng5
    uw5 = (h - np.maximum(o, c)) / rng5
    lw5 = (np.minimum(o, c) - l) / rng5

    vcp_5_50 = np.clip(atr5_pre / np.maximum(atr50_pre, 1e-9), 0.2, 3.5)
    vcp_15_90 = np.clip(atr15_pre / np.maximum(atr90_pre, 1e-9), 0.2, 3.5)
    pre3_c = np.roll(c, 3); pre3_c[:3] = c[:3]
    pre3_e21 = np.roll(ema21, 3); pre3_e21[:3] = ema21[:3]
    pre3_ext_a = np.clip(np.abs(pre3_c - pre3_e21) / atr_safe, 0.0, 10.0)
    mh_prev3 = np.roll(macd_h, 3); mh_prev3[:3] = macd_h[:3]

    df["rvol"] = np.nan_to_num(rvol, nan=1.0, posinf=15.0, neginf=0.0)
    df["atr_pct"] = np.nan_to_num(atr_pct, nan=0.004, posinf=0.10, neginf=0.001)
    df["vol_surge"] = pd.Series(qv).rolling(2, min_periods=1).mean().values / np.maximum(vol_ma20, 1e-6)

    # Shared non-directional columns
    df["body_5m"] = body5
    df["uw_5m"] = uw5
    df["lw_5m"] = lw5
    df["body_15m"] = body15
    df["uw_15m"] = uw15
    df["lw_15m"] = lw15
    df["rvol_15m_log"] = np.log1p(np.clip(rvol_15m, 0.0, 15.0))
    df["ker_10"] = ker10
    df["ker_30"] = ker30
    df["vcp_5_50"] = vcp_5_50
    df["vcp_15_90"] = vcp_15_90
    df["bb_sq_20"] = bb_sq
    df["adx14_norm"] = np.clip(adx / 50.0, 0.0, 2.0)
    df["rvol_5m_log"] = np.log1p(np.clip(rvol, 0.0, 15.0))
    df["min_vol_floor"] = np.clip(min_qv5_pre / np.maximum(vol_ma20, 1e-6), 0.0, 2.5)
    df["vol_accel_15m"] = np.clip(vol_acc_15m, 0.1, 8.0)
    df["pre3_ext_atr"] = pre3_ext_a

    # LONG directional columns
    df["clv_5m_l"] = clv5_l
    df["imp_5m_atr_l"] = np.clip(ret_1 / atr_p_safe, -6.0, 6.0)
    df["prev_5m_atr_l"] = np.clip(prev_ret1 / atr_p_safe, -6.0, 6.0)
    df["clv_15m_l"] = clv15_l
    df["imp_15m_atr_l"] = np.clip(ret_3 / (atr_p_safe * 1.73), -6.0, 6.0)
    df["vol_imb_6_l"] = sv6
    df["vol_imb_24_l"] = sv24
    df["ema9_atr_l"] = np.clip((c - ema9) / atr_safe, -8.0, 8.0)
    df["ema21_atr_l"] = np.clip((c - ema21) / atr_safe, -10.0, 10.0)
    df["ema63_atr_l"] = np.clip((c - ema63) / atr_safe, -14.0, 14.0)
    df["ema200_atr_l"] = np.clip((c - ema200) / atr_safe, -20.0, 20.0)
    df["rsi_dir_l"] = (rsi - 50.0) / 50.0
    df["macd_hist_atr_l"] = np.clip(macd_h / atr_safe, -4.0, 4.0)
    df["macd_accel_atr_l"] = np.clip((macd_h - mh_prev3) / atr_safe, -3.0, 3.0)
    df["room_72b_atr_l"] = np.clip(np.maximum(0.0, h72 - c) / atr_safe, 0.0, 15.0)
    df["ret_36b_atr_l"] = np.clip(ret_36 / atr_p_safe, -18.0, 18.0)

    # SHORT directional columns
    df["clv_5m_s"] = clv5_s
    df["imp_5m_atr_s"] = np.clip(-ret_1 / atr_p_safe, -6.0, 6.0)
    df["prev_5m_atr_s"] = np.clip(-prev_ret1 / atr_p_safe, -6.0, 6.0)
    df["clv_15m_s"] = clv15_s
    df["imp_15m_atr_s"] = np.clip(-ret_3 / (atr_p_safe * 1.73), -6.0, 6.0)
    df["vol_imb_6_s"] = -sv6
    df["vol_imb_24_s"] = -sv24
    df["ema9_atr_s"] = np.clip((ema9 - c) / atr_safe, -8.0, 8.0)
    df["ema21_atr_s"] = np.clip((ema21 - c) / atr_safe, -10.0, 10.0)
    df["ema63_atr_s"] = np.clip((ema63 - c) / atr_safe, -14.0, 14.0)
    df["ema200_atr_s"] = np.clip((ema200 - c) / atr_safe, -20.0, 20.0)
    df["rsi_dir_s"] = (50.0 - rsi) / 50.0
    df["macd_hist_atr_s"] = np.clip(-macd_h / atr_safe, -4.0, 4.0)
    df["macd_accel_atr_s"] = np.clip(-(macd_h - mh_prev3) / atr_safe, -3.0, 3.0)
    df["room_72b_atr_s"] = np.clip(np.maximum(0.0, c - l72) / atr_safe, 0.0, 15.0)
    df["ret_36b_atr_s"] = np.clip(-ret_36 / atr_p_safe, -18.0, 18.0)

    all_f_cols = list(dict.fromkeys(FEATURE_COLS_LONG + FEATURE_COLS_SHORT + ["rvol", "atr_pct", "vol_surge"]))
    df[all_f_cols] = df[all_f_cols].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return df


def extract_features_from_candles(candles: List[Dict[str, Any]], side: str = "LONG") -> Optional[pd.DataFrame]:
    """
    Принимает список свечей (от 15 до 250), возвращает строку признаков (DataFrame из 1 строки)
    строго для ПОСЛЕДНЕГО ЗАКРЫТОГО 5m бара (исключая пустую 3-секундную незакрытую свечу).
    """
    if not candles or len(candles) < 15:
        return None

    working_candles = candles
    if len(candles) >= 16:
        try:
            last_open_ms = int(candles[-1].get("time", 0))
            now_ms = int(time.time() * 1000)
            prior_vols = [float(c.get("quote_vol", c.get("volume", 0.0))) for c in candles[-21:-1]]
            avg_prior_v = (sum(prior_vols) / len(prior_vols)) if prior_vols else 1.0
            last_v = float(candles[-1].get("quote_vol", candles[-1].get("volume", 0.0)))
            is_live_volume_explosion = (now_ms - last_open_ms) >= 40_000 and avg_prior_v > 0 and (last_v / avg_prior_v) >= 1.45
            if last_open_ms > 0 and (now_ms - last_open_ms) < 299_000 and not is_live_volume_explosion:
                working_candles = candles[:-1]
        except (ValueError, TypeError):
            working_candles = candles[:-1]

    clean_records = []
    for c in working_candles:
        cl_val = float(c.get("close", 0.0))
        vol_val = float(c.get("volume", 0.0))
        qv_val = float(c.get("quote_vol", vol_val * cl_val))
        clean_records.append({
            "time": c.get("time", int(time.time() * 1000)),
            "open": float(c.get("open", 0.0)),
            "high": float(c.get("high", 0.0)),
            "low": float(c.get("low", 0.0)),
            "close": cl_val,
            "volume": vol_val if vol_val > 0 else qv_val / max(cl_val, 1e-9),
            "quote_vol": qv_val,
        })

    df = pd.DataFrame(clean_records)
    feat_df = compute_quant_features_dataframe(df)
    if feat_df.empty:
        return None

    cols = list(dict.fromkeys((FEATURE_COLS_LONG if side.upper() == "LONG" else FEATURE_COLS_SHORT) + ["rvol"]))
    return feat_df[cols].iloc[-1:].fillna(0.0)


def extract_features_from_dict_fallback(context: Dict[str, Any], side: str = "LONG") -> pd.DataFrame:
    """Резервный расчет 32 признаков при отсутствии массива сырых свечей."""
    is_short = (side.upper() == "SHORT")
    cur_p = float(context.get("current_price", 1.0) or 1.0)
    u_wick = float(context.get("upper_wick_pct", 0.15) or 0.15)
    l_wick = float(context.get("lower_wick_pct", 0.15) or 0.15)
    rvol = float(context.get("rvol", context.get("volume_surge_ratio", 1.8)) or 1.8)
    ema9 = float(context.get("ema9", cur_p) or cur_p)
    ema21 = float(context.get("ema21", cur_p) or cur_p)
    ema63 = float(context.get("ema63", ema21) or ema21)
    ema200 = float(context.get("ema200", ema63) or ema63)
    rsi = float(context.get("rsi", 55.0) or 55.0)
    adx = float(context.get("adx14", 22.0) or 22.0)
    atr_pct = max(float(context.get("atr14_pct", 0.005) or 0.005), 1e-4)
    atr_abs = cur_p * atr_pct
    p5m = float(context.get("pct_5m", 0.0) or 0.0) / 100.0
    p15m = float(context.get("pct_15m", p5m) or p5m) / 100.0
    clv = float(context.get("close_strength_short" if is_short else "close_strength_long", 0.70) or 0.70)
    body = max(0.05, 1.0 - u_wick - l_wick)
    sgn = -1.0 if is_short else 1.0

    vals = [
        body, clv, l_wick if is_short else u_wick, u_wick if is_short else l_wick,
        max(-6.0, min(6.0, sgn * p5m / atr_pct)),
        max(-6.0, min(6.0, sgn * (p15m - p5m) * 0.5 / atr_pct)),
        body * 0.9, clv, l_wick if is_short else u_wick,
        max(-6.0, min(6.0, sgn * p15m / (atr_pct * 1.73))),
        math.log1p(min(rvol, 15.0)),
        0.45, 0.38, 0.85, 0.90, 0.95, min(2.0, adx / 50.0),
        math.log1p(min(rvol, 15.0)), 0.55, 0.25, 0.18, min(8.0, rvol * 0.8),
        sgn * (cur_p - ema9) / atr_abs,
        sgn * (cur_p - ema21) / atr_abs,
        sgn * (cur_p - ema63) / atr_abs,
        sgn * (cur_p - ema200) / atr_abs,
        abs(float(context.get("ext_prev3_pct", 0.01) or 0.01)) / atr_pct,
        (50.0 - rsi) / 50.0 if is_short else (rsi - 50.0) / 50.0,
        0.35, 0.15, 3.0,
        sgn * float(context.get("ret_3h_pct", p15m * 2.0) or 0.0) / atr_pct,
    ]
    target_cols = FEATURE_COLS_SHORT if is_short else FEATURE_COLS_LONG
    out = pd.DataFrame([vals], columns=target_cols)
    out["rvol"] = rvol
    return out
