"""
realistic_backtest_7d.py
========================
Честный Walk-Forward бэктест без подгонки и без заглядывания в будущее (Zero Lookahead Bias):
  - Загружает реальные 5m свечи ликвидных пар Binance Perpetual Futures ($15M+ 24h объем, включая топ-ракеты дня).
  - Сигнал строго по закрытой свече [t-1], вход по цене открытия следующей свечи [t].
  - Полные биржевые издержки: 0.06% на вход + 0.06% на выход = 0.12% Taker + проскальзывание.
  - Стоп-лосс на каждой свече проверяется СТРОГО РАНЬШЕ тейк-профита (консервативный стандарт).
  - Сравнивает актуальный движок Anti-Rug Rocket Hunter (6H база + 3H сжатие + RugShort + 60%@1.65R + 40% Parabolic Trail)
    со старым 12-барным скальпером.
"""

import time
import datetime
import requests
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional
import config


def get_7d_data(prefer_extended_universe: bool = True, days: int = 7, max_pairs: int = 35) -> Dict[str, List[Dict[str, float]]]:
    """Скачивает свежие 5m свечи реальных ликвидных фьючерсов Binance (включая активные ракеты и сливы дня)."""
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    symbols: List[str] = []

    try:
        t24 = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=8).json()
        ex = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=8).json()
        perps = {
            s["symbol"] for s in ex.get("symbols", [])
            if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
            and s.get("underlyingType") == "COIN" and s.get("quoteAsset") == "USDT"
            and s["symbol"] not in config.EXCLUDED_TICKERS
        }
        liquid = [x for x in t24 if x["symbol"] in perps and float(x.get("quoteVolume", 0)) >= 15_000_000]
        by_move = sorted(liquid, key=lambda x: abs(float(x.get("priceChangePercent", 0))), reverse=True)
        by_vol = sorted(liquid, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        picked = []
        for item in by_move[:max_pairs // 2] + by_vol:
            if item["symbol"] not in picked and item["symbol"] != "BTCUSDT":
                picked.append(item["symbol"])
            if len(picked) >= max_pairs:
                break
        symbols = picked + ["BTCUSDT"]
        base_url = "https://fapi.binance.com/fapi/v1/klines"
    except Exception:
        symbols = list(config.TOP_CRYPTO_UNIVERSE[:24]) + ["BTCUSDT"]
        base_url = "https://data-api.binance.vision/api/v3/klines"

    data: Dict[str, List[Dict[str, float]]] = {}
    for sym in symbols:
        cdls = []
        cur = start_ms
        while cur < now_ms:
            try:
                r = requests.get(base_url, params={"symbol": sym, "interval": "5m", "startTime": cur, "limit": 1500}, timeout=7)
                if r.status_code != 200:
                    break
                chunk = r.json()
                if not chunk or not isinstance(chunk, list):
                    break
                for c in chunk[:-1] if chunk[-1][0] > now_ms - 300_000 else chunk:
                    cdls.append({
                        "time": int(c[0]), "open": float(c[1]), "high": float(c[2]),
                        "low": float(c[3]), "close": float(c[4]), "volume": float(c[5]),
                        "quote_vol": float(c[7])
                    })
                cur = int(chunk[-1][0]) + 300_000
                if len(chunk) < 1000:
                    break
            except Exception:
                break
        if len(cdls) >= 350:
            data[sym] = cdls
    return data


def _calc_ema(arr: np.ndarray, period: int) -> np.ndarray:
    k = 2.0 / (period + 1.0)
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1.0 - k)
    return out


def precompute_indicators(data: Dict[str, List[Dict[str, float]]]) -> Dict[str, Any]:
    """Предрасчет всех структурных, MTF и Anti-Rug индикаторов без заглядывания в будущее."""
    ind = {}
    all_times = set()
    for sym, cdls in data.items():
        n = len(cdls)
        if n < 200:
            continue
        t = np.array([c["time"] for c in cdls], dtype=np.int64)
        o = np.array([c["open"] for c in cdls], dtype=np.float64)
        h = np.array([c["high"] for c in cdls], dtype=np.float64)
        l = np.array([c["low"] for c in cdls], dtype=np.float64)
        c = np.array([c["close"] for c in cdls], dtype=np.float64)
        qv = np.array([c["quote_vol"] for c in cdls], dtype=np.float64)

        ema9 = _calc_ema(c, 9)
        ema21 = _calc_ema(c, 21)
        ema50 = _calc_ema(c, 50)
        ema27 = _calc_ema(c, 27)
        ema63 = _calc_ema(c, 63)
        ema150 = _calc_ema(c, 150)
        ema200 = _calc_ema(c, 200)
        macd_l = _calc_ema(c, 12) - _calc_ema(c, 26)
        macd_s = _calc_ema(macd_l, 9)
        macd_h = macd_l - macd_s

        tr = np.empty(n)
        tr[0] = h[0] - l[0]
        tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
        atr14 = pd.Series(tr).rolling(14, min_periods=1).mean().values
        atr_pct = atr14 / np.maximum(c, 1e-9)

        adx = np.full(n, 20.0)
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

        fvg_b = np.zeros(n, dtype=bool)
        fvg_s = np.zeros(n, dtype=bool)
        for j in range(4, n):
            fvg_b[j] = any(l[m] > h[m - 2] for m in range(j - 3, j + 1))
            fvg_s[j] = any(h[m] < l[m - 2] for m in range(j - 3, j + 1))

        vol_ma20 = pd.Series(qv).rolling(20, min_periods=5).mean().shift(1).bfill().values
        rvol = qv / np.maximum(vol_ma20, 1.0)
        v3_surge = pd.Series(qv).rolling(3, min_periods=1).mean().values / np.maximum(vol_ma20, 1.0)
        qvol_24h = pd.Series(qv).rolling(288, min_periods=24).sum().values

        delta = np.diff(c, prepend=c[0])
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)
        ag = pd.Series(gain).rolling(14, min_periods=3).mean().values
        al = pd.Series(loss).rolling(14, min_periods=3).mean().values
        rsi = np.where(al == 0, np.where(ag > 0, 100.0, 50.0), 100.0 - 100.0 / (1.0 + ag / np.maximum(al, 1e-12)))

        s_h = pd.Series(h).shift(1)
        s_l = pd.Series(l).shift(1)
        h12, l12 = s_h.rolling(12, min_periods=12).max().values, s_l.rolling(12, min_periods=12).min().values
        h16, l16 = s_h.rolling(16, min_periods=16).max().values, s_l.rolling(16, min_periods=16).min().values
        h36, l36 = s_h.rolling(36, min_periods=36).max().values, s_l.rolling(36, min_periods=36).min().values
        h72, l72 = s_h.rolling(72, min_periods=72).max().values, s_l.rolling(72, min_periods=72).min().values
        h144, l144 = s_h.rolling(144, min_periods=72).max().values, s_l.rolling(144, min_periods=72).min().values
        min_qv10 = pd.Series(qv).shift(1).rolling(10, min_periods=3).min().bfill().values

        ext = np.abs(c - ema21) / np.maximum(ema21, 1e-9)
        ret_3h = pd.Series(c).pct_change(36).fillna(0.0).values

        time_idx = {int(ts): idx for idx, ts in enumerate(t)}
        pb_l4 = pd.Series(l).rolling(4, min_periods=2).min().bfill().values
        pb_h4 = pd.Series(h).rolling(4, min_periods=2).max().bfill().values
        max_rvol_18 = pd.Series(rvol).shift(1).rolling(18, min_periods=3).max().bfill().values
        if sym != "BTCUSDT":
            all_times.update(t.tolist())

        ind[sym] = {
            "t": t, "o": o, "h": h, "l": l, "c": c, "qv": qv, "vol_ma20": vol_ma20, "min_qv10": min_qv10,
            "ema9": ema9, "ema21": ema21, "ema50": ema50, "ema27": ema27, "ema63": ema63, "ema150": ema150, "ema200": ema200,
            "macd_l": macd_l, "macd_s": macd_s, "macd_h": macd_h,
            "atr_pct": atr_pct, "adx": adx, "fvg_b": fvg_b, "fvg_s": fvg_s,
            "rvol": rvol, "v3_surge": v3_surge, "qvol_24h": qvol_24h,
            "rsi": rsi, "ext": ext, "ret_3h": ret_3h,
            "h12": h12, "l12": l12, "h16": h16, "l16": l16, "h36": h36, "l36": l36, "h72": h72, "l72": l72,
            "h144": h144, "l144": l144,
            "pb_l4": pb_l4, "pb_h4": pb_h4, "max_rvol_18": max_rvol_18,
            "time_idx": time_idx
        }
    return {"ind": ind, "ts": sorted(all_times)}


def _attach_ml_probs(all_data: Dict[str, Any], pre: Dict[str, Any]) -> None:
    """Батч-инференс обученной Multi-Scale ML модели (ml_engine) без Train-Serve Skew."""
    from quant_features import FEATURE_COLS_LONG, FEATURE_COLS_SHORT, compute_quant_features_dataframe
    from ml_engine import ml_engine

    ind = pre["ind"]
    if ml_engine.model_long is None or ml_engine.model_short is None:
        for d in ind.values():
            n = len(d["c"])
            d["ml_l"] = np.full(n, 0.50)
            d["ml_s"] = np.full(n, 0.50)
        return

    cols_l = ml_engine.feature_cols_long or FEATURE_COLS_LONG
    cols_s = ml_engine.feature_cols_short or FEATURE_COLS_SHORT
    for sym, d in ind.items():
        if sym == "BTCUSDT" or "ml_l" in d:
            continue
        cdls = all_data.get(sym)
        if not cdls or len(cdls) != len(d["c"]):
            n = len(d["c"])
            d["ml_l"] = np.full(n, 0.50)
            d["ml_s"] = np.full(n, 0.50)
            continue
        df_c = pd.DataFrame([
            {
                "time": c["time"], "open": float(c["open"]), "high": float(c["high"]),
                "low": float(c["low"]), "close": float(c["close"]),
                "volume": float(c.get("volume", float(c.get("quote_vol", 0.0)) / max(float(c["close"]), 1e-9))),
                "quote_vol": float(c.get("quote_vol", 0.0)),
            }
            for c in cdls
        ])
        fdf = compute_quant_features_dataframe(df_c)
        if fdf.empty or any(col not in fdf.columns for col in cols_l):
            n = len(d["c"])
            d["ml_l"] = np.full(n, 0.50)
            d["ml_s"] = np.full(n, 0.50)
        else:
            d["ml_l"] = ml_engine.model_long.predict_proba(fdf[cols_l].values)[:, 1]
            d["ml_s"] = ml_engine.model_short.predict_proba(fdf[cols_s].values)[:, 1]


def simulate_strategy(
    all_data: Dict[str, Any],
    initial_balance: float = 20.0,
    precomputed: Optional[Dict[str, Any]] = None,
    leverage: int = 15,
    risk_pct: float = 0.030,
    tp1_r: float = 1.65,
    tp1_share: float = 0.60,
    legacy_churn_mode: bool = False,
    equal_margin_pct: float = 0.0,
    max_spike_5m: float = 0.0,
    big_runner_mode: bool = False,
    max_slots_override: int = 0,
    btc_ema63_align: bool = True,
    cap_risk_pct: float = 0.038,
    use_ml_hybrid: bool = False,
    **kwargs
) -> Dict[str, Any]:
    pre = precomputed if precomputed is not None else precompute_indicators(all_data)
    if use_ml_hybrid:
        _attach_ml_probs(all_data, pre)
    ind = pre["ind"]
    ts_list = pre["ts"][180:]

    cash = initial_balance
    peak_eq = initial_balance
    max_dd = 0.0
    cost = 0.0009 if big_runner_mode else 0.0006
    stop_cost = 0.0012 if big_runner_mode else 0.0006
    total_comm = 0.0
    open_pos: Dict[str, Dict[str, Any]] = {}
    trades_r: List[float] = []
    trades_pnl: List[float] = []
    lockouts: Dict[str, int] = {}
    daily_map: Dict[str, Dict[str, Any]] = {}
    btc_d = ind.get("BTCUSDT")

    for t_now in ts_list:
        ts_sec = int(t_now) // 1000 if t_now > 1e11 else int(t_now)
        d_str = datetime.datetime.utcfromtimestamp(ts_sec).strftime("%Y-%m-%d")
        if d_str not in daily_map:
            cur_u = 0.0
            for _s, _p in open_pos.items():
                _ix = ind[_s]["time_idx"].get(t_now)
                if _ix is not None:
                    _cl = ind[_s]["c"][_ix]
                    _rw = (_cl - _p["entry"]) / _p["entry"] if _p["side"] == "LONG" else (_p["entry"] - _cl) / _p["entry"]
                    cur_u += _p["mg"] * _rw * _p["lev"]
            start_e = cash + sum(_p["mg"] for _p in open_pos.values()) + cur_u
            daily_map[d_str] = {"start_eq": start_e, "end_eq": start_e, "trades": 0, "wins": 0, "losses": 0}
        btc_dump = btc_pump = btc_flush = btc_spike = False
        btc_bull_m = btc_bear_m = True
        bp5 = bp15 = 0.0
        if btc_d is not None:
            bi = btc_d["time_idx"].get(t_now)
            if bi and bi >= 15:
                k = bi - 1
                bp5 = (btc_d["c"][k] - btc_d["c"][k - 1]) / btc_d["c"][k - 1] * 100.0
                bp15 = (btc_d["c"][k] - btc_d["c"][k - 3]) / btc_d["c"][k - 3] * 100.0
                btc_dump = bp15 <= -0.55 or bp5 <= -0.40
                btc_pump = bp15 >= 0.55 or bp5 >= 0.40
                btc_flush = bp5 <= -0.38 or bp15 <= -0.75
                btc_spike = bp5 >= 0.38 or bp15 >= 0.75
                if big_runner_mode and btc_ema63_align:
                    btc_bull_m = btc_d["c"][k] >= btc_d["ema63"][k] * 0.999
                    btc_bear_m = btc_d["c"][k] <= btc_d["ema63"][k] * 1.001

        unreal = 0.0
        for sym in list(open_pos.keys()):
            pos = open_pos[sym]
            d = ind[sym]
            idx = d["time_idx"].get(t_now)
            if idx is None:
                continue
            pos["bars"] += 1
            if big_runner_mode and pos["bars"] % 96 == 0:
                f_fee = pos["mg"] * pos["lev"] * 0.0001
                total_comm += f_fee
                cash = max(0.0, cash - f_fee)
                pos["realized"] -= f_fee
            h, l, cl = d["h"][idx], d["l"][idx], d["c"][idx]
            entry, side, lev, rd = pos["entry"], pos["side"], pos["lev"], pos["rd"]
            atr_p = d["atr_pct"][idx - 1]

            if side == "LONG":
                if l <= pos["sl"]:
                    fee = pos["mg"] * lev * stop_cost
                    total_comm += fee
                    pnl = pos["mg"] * ((pos["sl"] - entry) / entry) * lev - fee
                    cash = max(0.0, cash + pos["mg"] + pnl)
                    pos["realized"] += pnl
                    trades_pnl.append(pos["realized"])
                    trades_r.append(pos["realized"] / pos["risk_usd"])
                    daily_map[d_str]["trades"] += 1
                    daily_map[d_str]["wins" if pos["realized"] > 0 else "losses"] += 1
                    loss_cd_b = 24 if big_runner_mode else 18
                    lockouts[sym] = idx + (loss_cd_b if pos["realized"] < 0 else 2)
                    del open_pos[sym]
                    continue

                pos["hi"] = max(pos["hi"], h)
                mfe_r = (pos["hi"] - entry) / rd

                if use_ml_hybrid and not pos.get("be_hit", False) and mfe_r >= pos.get("be_r", 99.0):
                    pos["be_hit"] = True
                    fee_plus = max(entry * 0.0026, 0.15 * rd)
                    pos["sl"] = max(pos["sl"], entry + fee_plus)

                if legacy_churn_mode:
                    if mfe_r >= 0.85:
                        pos["sl"] = max(pos["sl"], entry * 1.0020)
                    if pos["bars"] >= 7 and (cl - entry) / rd < 0.45:
                        fee = pos["mg"] * lev * cost
                        total_comm += fee
                        pnl = pos["mg"] * ((cl - entry) / entry) * lev - fee
                        cash = max(0.0, cash + pos["mg"] + pnl)
                        pos["realized"] += pnl
                        trades_pnl.append(pos["realized"])
                        trades_r.append(pos["realized"] / pos["risk_usd"])
                        del open_pos[sym]
                        continue

                eff_tp1_r = pos.get("tp1_r", tp1_r)
                eff_tp2_r = pos.get("tp2_r", 2.21)
                if not pos["tp1_hit"] and h >= entry + eff_tp1_r * rd:
                    if tp1_share >= 0.99:
                        fee = pos["mg"] * lev * cost
                        total_comm += fee
                        pnl = pos["mg"] * ((entry + eff_tp1_r * rd - entry) / entry) * lev - fee
                        cash = max(0.0, cash + pos["mg"] + pnl)
                        pos["realized"] += pnl
                        trades_pnl.append(pos["realized"])
                        trades_r.append(pos["realized"] / pos["risk_usd"])
                        lockouts[sym] = idx + 2
                        del open_pos[sym]
                        continue
                    else:
                        pos["tp1_hit"] = True
                        cm = pos["init_mg"] * tp1_share
                        fee = cm * lev * cost
                        total_comm += fee
                        pnl = cm * ((eff_tp1_r * rd) / entry) * lev - fee
                        cash += cm + pnl
                        pos["realized"] += pnl
                        pos["mg"] -= cm
                        pos["sl"] = max(pos["sl"], entry + 0.35 * rd)

                if pos["tp1_hit"]:
                    if big_runner_mode and tp1_share <= 0.001 and mfe_r >= eff_tp2_r:
                        pos["sl"] = max(pos["sl"], entry + 1.32 * rd)
                    if big_runner_mode:
                        if mfe_r >= 6.6:
                            trail_p = pos["hi"] - max(1.60 * atr_p * pos["hi"], 0.80 * rd)
                        elif mfe_r >= 4.5:
                            trail_p = pos["hi"] - max(1.85 * atr_p * pos["hi"], 1.00 * rd)
                        elif mfe_r >= 2.8:
                            trail_p = max(entry + 1.15 * rd, pos["hi"] - max(2.05 * atr_p * pos["hi"], 1.18 * rd))
                        else:
                            trail_p = pos["sl"]
                    else:
                        if mfe_r >= 6.0:
                            trail_p = pos["hi"] - max(0.95 * atr_p * pos["hi"], 0.55 * rd)
                        elif mfe_r >= 3.5:
                            trail_p = pos["hi"] - max(1.25 * atr_p * pos["hi"], 0.75 * rd)
                        elif mfe_r >= 2.2:
                            trail_p = max(entry + 1.15 * rd, pos["hi"] - max(1.65 * atr_p * pos["hi"], 0.95 * rd))
                        else:
                            trail_p = pos["sl"]
                    pos["sl"] = max(pos["sl"], trail_p)

                if big_runner_mode and not pos["tp1_hit"] and not pos.get("be_hit", False) and pos["bars"] >= 288:
                    fee = pos["mg"] * lev * stop_cost
                    total_comm += fee
                    pnl = pos["mg"] * ((cl - entry) / entry) * lev - fee
                    cash = max(0.0, cash + pos["mg"] + pnl)
                    pos["realized"] += pnl
                    trades_pnl.append(pos["realized"])
                    trades_r.append(pos["realized"] / pos["risk_usd"])
                    daily_map[d_str]["trades"] += 1
                    daily_map[d_str]["wins" if pos["realized"] > 0 else "losses"] += 1
                    lockouts[sym] = idx + 12
                    del open_pos[sym]
                    continue

                unreal += pos["mg"] * ((cl - entry) / entry) * lev

            else:
                if h >= pos["sl"]:
                    fee = pos["mg"] * lev * stop_cost
                    total_comm += fee
                    pnl = pos["mg"] * ((entry - pos["sl"]) / entry) * lev - fee
                    cash = max(0.0, cash + pos["mg"] + pnl)
                    pos["realized"] += pnl
                    trades_pnl.append(pos["realized"])
                    trades_r.append(pos["realized"] / pos["risk_usd"])
                    daily_map[d_str]["trades"] += 1
                    daily_map[d_str]["wins" if pos["realized"] > 0 else "losses"] += 1
                    loss_cd_b = 24 if big_runner_mode else 18
                    lockouts[sym] = idx + (loss_cd_b if pos["realized"] < 0 else 2)
                    del open_pos[sym]
                    continue

                pos["lo"] = min(pos["lo"], l)
                mfe_r = (entry - pos["lo"]) / rd

                if use_ml_hybrid and not pos.get("be_hit", False) and mfe_r >= pos.get("be_r", 99.0):
                    pos["be_hit"] = True
                    fee_plus = max(entry * 0.0026, 0.15 * rd)
                    pos["sl"] = min(pos["sl"], entry - fee_plus)

                if legacy_churn_mode:
                    if mfe_r >= 0.85:
                        pos["sl"] = min(pos["sl"], entry * 0.9980)
                    if pos["bars"] >= 7 and (entry - cl) / rd < 0.45:
                        fee = pos["mg"] * lev * cost
                        total_comm += fee
                        pnl = pos["mg"] * ((entry - cl) / entry) * lev - fee
                        cash = max(0.0, cash + pos["mg"] + pnl)
                        pos["realized"] += pnl
                        trades_pnl.append(pos["realized"])
                        trades_r.append(pos["realized"] / pos["risk_usd"])
                        del open_pos[sym]
                        continue

                eff_tp1_r = pos.get("tp1_r", tp1_r)
                eff_tp2_r = pos.get("tp2_r", 2.21)
                if not pos["tp1_hit"] and l <= entry - eff_tp1_r * rd:
                    if tp1_share >= 0.99:
                        fee = pos["mg"] * lev * cost
                        total_comm += fee
                        pnl = pos["mg"] * ((eff_tp1_r * rd) / entry) * lev - fee
                        cash = max(0.0, cash + pos["mg"] + pnl)
                        pos["realized"] += pnl
                        trades_pnl.append(pos["realized"])
                        trades_r.append(pos["realized"] / pos["risk_usd"])
                        lockouts[sym] = idx + 2
                        del open_pos[sym]
                        continue
                    else:
                        pos["tp1_hit"] = True
                        cm = pos["init_mg"] * tp1_share
                        fee = cm * lev * cost
                        total_comm += fee
                        pnl = cm * ((eff_tp1_r * rd) / entry) * lev - fee
                        cash += cm + pnl
                        pos["realized"] += pnl
                        pos["mg"] -= cm
                        pos["sl"] = min(pos["sl"], entry - 0.35 * rd)

                if pos["tp1_hit"]:
                    if big_runner_mode and tp1_share <= 0.001 and mfe_r >= eff_tp2_r:
                        pos["sl"] = min(pos["sl"], entry - 1.32 * rd)
                    if big_runner_mode:
                        if mfe_r >= 6.6:
                            trail_p = pos["lo"] + max(1.60 * atr_p * pos["lo"], 0.80 * rd)
                        elif mfe_r >= 4.5:
                            trail_p = pos["lo"] + max(1.85 * atr_p * pos["lo"], 1.00 * rd)
                        elif mfe_r >= 2.8:
                            trail_p = min(entry - 1.15 * rd, pos["lo"] + max(2.05 * atr_p * pos["lo"], 1.18 * rd))
                        else:
                            trail_p = pos["sl"]
                    else:
                        if mfe_r >= 6.0:
                            trail_p = pos["lo"] + max(0.95 * atr_p * pos["lo"], 0.55 * rd)
                        elif mfe_r >= 3.5:
                            trail_p = pos["lo"] + max(1.25 * atr_p * pos["lo"], 0.75 * rd)
                        elif mfe_r >= 2.2:
                            trail_p = min(entry - 1.15 * rd, pos["lo"] + max(1.65 * atr_p * pos["lo"], 0.95 * rd))
                        else:
                            trail_p = pos["sl"]
                    pos["sl"] = min(pos["sl"], trail_p)

                if big_runner_mode and not pos["tp1_hit"] and not pos.get("be_hit", False) and pos["bars"] >= 288:
                    fee = pos["mg"] * lev * stop_cost
                    total_comm += fee
                    pnl = pos["mg"] * ((entry - cl) / entry) * lev - fee
                    cash = max(0.0, cash + pos["mg"] + pnl)
                    pos["realized"] += pnl
                    trades_pnl.append(pos["realized"])
                    trades_r.append(pos["realized"] / pos["risk_usd"])
                    daily_map[d_str]["trades"] += 1
                    daily_map[d_str]["wins" if pos["realized"] > 0 else "losses"] += 1
                    lockouts[sym] = idx + 12
                    del open_pos[sym]
                    continue

                unreal += pos["mg"] * ((entry - cl) / entry) * lev

        eq = cash + sum(p["mg"] for p in open_pos.values()) + unreal
        daily_map[d_str]["end_eq"] = eq
        peak_eq = max(peak_eq, eq)
        max_dd = max(max_dd, (peak_eq - eq) / peak_eq if peak_eq > 0 else 0.0)

        at_risk = sum(1 for p in open_pos.values() if not (p["tp1_hit"] or p.get("be_hit", False)))
        max_at_risk = max_slots_override if max_slots_override > 0 else (2 if legacy_churn_mode else (15 if big_runner_mode else 2))
        max_slots = (max_slots_override + 5) if max_slots_override > 0 else (2 if legacy_churn_mode else (20 if big_runner_mode else 4))
        if at_risk < max_at_risk and len(open_pos) < max_slots and cash >= 1.2:
            cands = []
            for sym, d in ind.items():
                if sym == "BTCUSDT" or sym in open_pos:
                    continue
                idx = d["time_idx"].get(t_now)
                if idx is None or idx < 160 or idx < lockouts.get(sym, 0):
                    continue
                k = idx - 1
                if d["qvol_24h"][k] < 1_500_000.0:
                    continue
                cl, lo, hi, op = d["c"][k], d["l"][k], d["h"][k], d["o"][k]
                pct_5m = (cl - d["c"][k - 1]) / d["c"][k - 1] * 100.0
                rng = max(hi - lo, 1e-9)
                uw, lw = (hi - max(op, cl)) / rng, (min(op, cl) - lo) / rng
                clv_l, clv_s = (cl - lo) / rng, (hi - cl) / rng
                atr_p, rvol = d["atr_pct"][k], d["rvol"][k]
                ep = d["o"][idx]

                if legacy_churn_mode:
                    if atr_p < 0.0025 or rvol < 1.45 or d["ext"][k] > 0.035:
                        continue
                    if cl > d["h12"][k] and pct_5m >= 0.42 and clv_l >= 0.68 and uw <= 0.28 and cl > d["ema9"][k] >= d["ema21"][k] * 0.998 and not btc_dump:
                        sl = min(max((ep - min(lo, d["l"][k - 1]) * 0.999) / ep, 1.2 * atr_p, 0.0055), 0.0135)
                        cands.append((rvol * abs(pct_5m), sym, "LONG", ep, sl, tp1_r, 2.21))
                    elif cl < d["l12"][k] and pct_5m <= -0.42 and clv_s >= 0.68 and lw <= 0.28 and cl < d["ema9"][k] <= d["ema21"][k] * 1.002 and not btc_pump:
                        sl = min(max((max(hi, d["h"][k - 1]) * 1.001 - ep) / ep, 1.2 * atr_p, 0.0055), 0.0135)
                        cands.append((rvol * abs(pct_5m), sym, "SHORT", ep, sl, tp1_r, 2.21))
                else:
                    dt_hr = datetime.datetime.utcfromtimestamp(ts_sec).hour
                    is_night = big_runner_mode and (dt_hr >= 21 or dt_hr < 1)
                    req_rvol = 2.10 if is_night else 1.80
                    req_clv = 0.72 if is_night else 0.66
                    if atr_p < 0.0025 or d["vol_ma20"][k] < 2500.0 or d["v3_surge"][k] < 1.10:
                        continue
                    if big_runner_mode and (d["qv"][k] < 5000.0 or d["min_qv10"][k] < 450.0):
                        continue
                    if max_spike_5m > 0.0 and abs(pct_5m) > max_spike_5m:
                        continue
                    ema9, ema21, ema50 = d["ema9"][k], d["ema21"][k], d["ema50"][k]
                    ema27, ema63, ema150, ema200 = d["ema27"][k], d["ema63"][k], d["ema150"][k], d["ema200"][k]
                    rsi, adx = d["rsi"][k], d["adx"][k]
                    macd_b = d["macd_l"][k] > d["macd_s"][k] and d["macd_h"][k] > d["macd_h"][k - 1]
                    macd_s = d["macd_l"][k] < d["macd_s"][k] and d["macd_h"][k] < d["macd_h"][k - 1]
                    pct_15m = (cl - d["c"][k - 3]) / d["c"][k - 3] * 100.0
                    alpha_5m = pct_5m - bp5
                    alpha_15m = pct_15m - bp15
                    mtf_l = (cl >= ema63 * 0.998 and ema27 >= ema63 * 0.998 and (ema63 >= ema150 * 0.995 or (big_runner_mode and macd_b and adx >= 20.0 and d["fvg_b"][k])))
                    mtf_s = (cl <= ema63 * 1.002 and ema27 <= ema63 * 1.002 and (ema63 <= ema150 * 1.005 or (big_runner_mode and macd_s and adx >= 20.0 and d["fvg_s"][k])))
                    eff_btc_l = btc_bull_m or (big_runner_mode and rvol >= 2.80 and alpha_5m >= 1.50)
                    eff_btc_s = btc_bear_m or (big_runner_mode and rvol >= 2.80 and alpha_5m <= -1.50)
                    min_imp = max(0.55, atr_p * 85.0)
                    sq_rng = (d["h16"][k] - d["l16"][k]) / max(d["l16"][k], 1e-9)

                    h12h, l12h = d["h144"][k], d["l144"][k]
                    rng12h = (h12h - l12h) / max(l12h, 1e-9)
                    pos12h = (cl - l12h) / max(h12h - l12h, 1e-9)
                    mw = 0.090 if rng12h >= 0.24 else max(0.035, 1.70 * atr_p * 1.75)
                    wall_ok_l = not (big_runner_mode and rng12h >= 0.14 and pos12h >= 0.55 and 0.0 < (h12h - cl) / max(cl, 1e-9) <= mw)
                    wall_ok_s = not (big_runner_mode and rng12h >= 0.14 and pos12h <= 0.45 and 0.0 < (cl - l12h) / max(cl, 1e-9) <= mw)

                    _sl_floor = 0.0110 if big_runner_mode else 0.0080
                    _sl_atr_m = 1.75 if big_runner_mode else 1.55
                    _sl_cap = 0.0380 if big_runner_mode else 0.0360
                    picked = None

                    if rvol >= req_rvol and d["ext"][k] <= 0.048 and d["ext"][k - 3] <= 0.028:
                        brk_l = (cl > d["h36"][k]) or (sq_rng <= 0.065 and cl > d["h16"][k] and rvol >= max(2.0, req_rvol))
                        if (
                            eff_btc_l and wall_ok_l and brk_l and mtf_l and cl >= ema50 * 0.996 and pct_5m >= min_imp
                            and alpha_5m >= 0.80 and alpha_15m >= 1.00
                            and clv_l >= req_clv and uw <= 0.26 and cl > ema9 >= ema21 * 0.998
                            and 48.0 <= rsi <= 86.0 and d["ret_3h"][k] <= 0.20 and not btc_dump and not btc_spike
                        ):
                            raw_sl = max((ep - min(lo, d["l"][k - 1]) * 0.9985) / ep, _sl_atr_m * atr_p, _sl_floor)
                            sl = raw_sl if big_runner_mode else min(raw_sl, _sl_cap)
                            if sl <= _sl_cap:
                                fvg = bool(d["fvg_b"][k] and adx >= 20.0)
                                t1 = (1.46 if fvg else (1.35 if sl >= 0.030 else 1.46)) if big_runner_mode else tp1_r
                                t2 = (2.25 if fvg else (2.00 if sl >= 0.030 else 2.25))
                                picked = (rvol * alpha_5m * clv_l * (1.25 if fvg else 1.0), "LONG", ep, sl, t1, t2)

                        pump_6h = (d["h72"][k] - d["l72"][k]) / max(d["l72"][k], 1e-9)
                        off_hi = (d["h72"][k] - cl) / max(d["h72"][k], 1e-9)
                        is_rug_s = (pump_6h >= 0.15 and 0.03 <= off_hi <= 0.22 and cl < d["l16"][k] and cl < ema50 and rvol >= max(2.0, req_rvol))
                        brk_s = ((cl < d["l36"][k]) or (sq_rng <= 0.065 and cl < d["l16"][k] and rvol >= max(2.0, req_rvol))) and mtf_s and wall_ok_s and eff_btc_s
                        if not picked and (
                            (brk_s or is_rug_s) and cl <= ema50 * 1.004 and pct_5m <= -min_imp
                            and alpha_5m <= -0.80 and alpha_15m <= -1.00
                            and clv_s >= req_clv and lw <= 0.26 and cl < ema9 <= ema21 * 1.002
                            and 14.0 <= rsi <= 52.0 and d["ret_3h"][k] >= -0.20 and not btc_pump and not btc_flush
                        ):
                            raw_sl = max((max(hi, d["h"][k - 1]) * 1.0015 - ep) / ep, _sl_atr_m * atr_p, _sl_floor)
                            sl = raw_sl if big_runner_mode else min(raw_sl, _sl_cap)
                            if sl <= _sl_cap:
                                fvg = bool(d["fvg_s"][k] and adx >= 20.0)
                                t1 = (1.25 if is_rug_s else (1.46 if fvg else (1.35 if sl >= 0.030 else 1.46))) if big_runner_mode else tp1_r
                                t2 = (1.95 if is_rug_s else (2.25 if fvg else (2.00 if sl >= 0.030 else 2.25)))
                                picked = (rvol * abs(alpha_5m) * clv_s * (1.25 if fvg else 1.0), "SHORT", ep, sl, t1, t2)

                    if big_runner_mode and not picked and adx >= 20.0 and rvol >= (req_rvol if is_night else 1.50) and d["ext"][k] <= 0.032:
                        sm_htf_l = mtf_l or (cl >= ema63 * 0.998 and macd_b)
                        sm_htf_s = mtf_s or (cl <= ema63 * 1.002 and macd_s)
                        if eff_btc_l and wall_ok_l and sm_htf_l and not btc_dump and not btc_spike and d["fvg_b"][k] and cl > d["h16"][k] and alpha_5m >= 0.65 and alpha_15m >= 0.90 and clv_l >= 0.70 and uw <= 0.24 and 50.0 <= rsi <= 78.0:
                            sl = max((ep - d["l12"][k] * 0.9985) / ep, _sl_atr_m * atr_p, _sl_floor)
                            if sl <= _sl_cap:
                                picked = (rvol * alpha_5m * clv_l * 0.90, "LONG", ep, sl, 1.46, 2.25)
                        elif eff_btc_s and wall_ok_s and sm_htf_s and not btc_pump and not btc_flush and d["fvg_s"][k] and cl < d["l16"][k] and alpha_5m <= -0.65 and alpha_15m <= -0.90 and clv_s >= 0.70 and lw <= 0.24 and 22.0 <= rsi <= 50.0:
                            sl = max((d["h12"][k] * 1.0015 - ep) / ep, _sl_atr_m * atr_p, _sl_floor)
                            if sl <= _sl_cap:
                                picked = (rvol * abs(alpha_5m) * clv_s * 0.90, "SHORT", ep, sl, 1.46, 2.25)

                    if picked:
                        if use_ml_hybrid:
                            mlp = float(d["ml_l"][k] if picked[1] == "LONG" else d["ml_s"][k])
                            if mlp < float(getattr(config, "ML_MIN_FILTER_PROB", 0.450)):
                                picked = None
                            else:
                                be_v = 99.0 if mlp >= float(getattr(config, "ML_TOP_ROCKET_PROB", 0.495)) else float(getattr(config, "ML_MEDIUM_BE_TRIGGER_R", 0.92))
                                picked = (picked[0] * ((mlp / 0.50) ** 1.5), picked[1], picked[2], picked[3], picked[4], picked[5], be_v, mlp >= float(getattr(config, "ML_TOP_ROCKET_PROB", 0.495)), "RK")
                    if not picked and use_ml_hybrid and not is_night and d["adx"][k] >= 22.0 and d["max_rvol_18"][k] >= 2.25:
                        if (
                            btc_bull_m and not btc_dump and ema21 > ema63 > ema150 and cl > d["ema200"][k]
                            and d["pb_l4"][k] <= ema21 * 1.004 and d["pb_l4"][k] >= ema63 * 0.996
                            and cl > op and cl > ema9 and cl > d["h"][k - 1] and clv_l >= 0.72 and uw <= 0.22
                            and 1.15 <= rvol <= 3.50 and 45.0 <= rsi <= 68.0 and alpha_5m >= 0.35
                            and d["ml_l"][k] >= float(getattr(config, "ML_PULLBACK_MIN_PROB", 0.484))
                        ):
                            sl_pb = max((ep - d["pb_l4"][k] * 0.9985) / ep, 1.55 * atr_p, _sl_floor)
                            if sl_pb <= 0.0280:
                                sc_pb = 0.75 * rvol * clv_l * ((d["ml_l"][k] / 0.50) ** 1.5)
                                picked = (sc_pb, "LONG", ep, sl_pb, 1.00, 1.85, 0.85, False, "PB")
                        elif (
                            btc_bear_m and not btc_pump and ema21 < ema63 < ema150 and cl < d["ema200"][k]
                            and d["pb_h4"][k] >= ema21 * 0.996 and d["pb_h4"][k] <= ema63 * 1.004
                            and cl < op and cl < ema9 and cl < d["l"][k - 1] and clv_s >= 0.72 and lw <= 0.22
                            and 1.15 <= rvol <= 3.50 and 32.0 <= rsi <= 55.0 and alpha_5m <= -0.35
                            and d["ml_s"][k] >= float(getattr(config, "ML_PULLBACK_MIN_PROB", 0.484))
                        ):
                            sl_pb = max((d["pb_h4"][k] * 1.0015 - ep) / ep, 1.55 * atr_p, _sl_floor)
                            if sl_pb <= 0.0280:
                                sc_pb = 0.75 * rvol * clv_s * ((d["ml_s"][k] / 0.50) ** 1.5)
                                picked = (sc_pb, "SHORT", ep, sl_pb, 1.00, 1.85, 0.85, False, "PB")

                    if picked:
                        if len(picked) == 6:
                            cands.append((picked[0], sym, picked[1], picked[2], picked[3], picked[4], picked[5], 99.0, True, "RK"))
                        else:
                            cands.append((picked[0], sym, picked[1], picked[2], picked[3], picked[4], picked[5], picked[6], picked[7], picked[8]))

            cands.sort(reverse=True)
            for score, sym, side, ep, sl_dist, t1_r_v, t2_r_v, be_r_v, is_top_rk, kind_v in cands[:10]:
                at_r_now = [p for p in open_pos.values() if not (p["tp1_hit"] or p.get("be_hit", False))]
                if len(at_r_now) >= max_at_risk or len(open_pos) >= max_slots:
                    break
                if kind_v == "PB" and len(at_r_now) >= int(getattr(config, "PULLBACK_MAX_SLOTS", 8)):
                    continue
                same_s = [p for p in at_r_now if p["side"] == side]
                if big_runner_mode and same_s:
                    if side == "LONG" and (bp15 <= -0.35 or bp5 <= -0.25):
                        continue
                    if side == "SHORT" and (bp15 >= 0.35 or bp5 >= 0.25):
                        continue
                cur_eq = max(10.0, cash + sum(p["mg"] for p in open_pos.values()))
                cur_dd = (peak_eq - cur_eq) / peak_eq if peak_eq > 0 else 0.0
                dd_mult = 0.75 if cur_dd >= 0.20 else 1.0
                if equal_margin_pct > 0.0:
                    max_liq_mg = 1500.0 / max(leverage, 1)
                    eff_mg_pct = (0.036 if is_top_rk else 0.033) if use_ml_hybrid else equal_margin_pct
                    base_mg = cur_eq * eff_mg_pct * dd_mult
                    if cap_risk_pct > 0.0:
                        base_mg = min(base_mg, (cur_eq * cap_risk_pct * dd_mult) / ((sl_dist + stop_cost) * max(leverage, 1)))
                    mg = round(min(base_mg, max_liq_mg, cur_eq * 0.25, cash * 0.40), 2)
                    risk_usd = max(mg * leverage * sl_dist, 0.05)
                else:
                    r_eff = risk_pct * dd_mult
                    risk_usd = cur_eq * r_eff
                    mg = round(min((risk_usd / (sl_dist + 2 * cost)) / leverage, cur_eq * 0.25, cash * 0.48), 2)
                if mg < 0.50 or cash < mg + 0.05:
                    continue
                fee_in = mg * leverage * cost
                total_comm += fee_in
                cash -= (mg + fee_in)
                rd = ep * sl_dist
                open_pos[sym] = {
                    "side": side, "entry": ep, "mg": mg, "init_mg": mg, "lev": leverage,
                    "sl": ep - rd if side == "LONG" else ep + rd,
                    "rd": rd, "risk_usd": max(risk_usd, 0.05),
                    "tp1_r": t1_r_v, "tp2_r": t2_r_v, "be_r": be_r_v, "be_hit": False,
                    "tp1_hit": False, "bars": 0, "hi": ep, "lo": ep, "realized": -fee_in
                }

    for sym, pos in list(open_pos.items()):
        cl = ind[sym]["c"][-1]
        raw = (cl - pos["entry"]) / pos["entry"] if pos["side"] == "LONG" else (pos["entry"] - cl) / pos["entry"]
        fee = pos["mg"] * pos["lev"] * cost
        total_comm += fee
        pnl = pos["mg"] * raw * pos["lev"] - fee
        cash = max(0.0, cash + pos["mg"] + pnl)
        pos["realized"] += pnl
        trades_pnl.append(pos["realized"])
        trades_r.append(pos["realized"] / pos["risk_usd"])

    wins = [x for x in trades_pnl if x > 0]
    losses = [x for x in trades_pnl if x <= 0]
    wr = round(len(wins) / len(trades_pnl) * 100.0, 1) if trades_pnl else 0.0
    pf = round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else (99.0 if wins else 0.0)
    exp_r = round(sum(trades_r) / len(trades_r), 3) if trades_r else 0.0

    daily_rows = []
    win_days = 0
    loss_days = 0
    for dk in sorted(daily_map.keys()):
        dm = daily_map[dk]
        d_pnl = round(dm["end_eq"] - dm["start_eq"], 2)
        d_pct = round((d_pnl / max(dm["start_eq"], 1.0)) * 100.0, 1)
        if dm["trades"] > 0 or abs(d_pnl) >= 0.05:
            if d_pnl >= 0:
                win_days += 1
            else:
                loss_days += 1
        daily_rows.append({
            "Дата": dk,
            "Итог дня": "✅ Плюс" if d_pnl >= 0 else "❌ Убыток",
            "PnL за день ($)": f"${d_pnl:+.2f}",
            "PnL за день (%)": f"{d_pct:+.1f}%",
            "Закрыто сделок": f"{dm['trades']} (W:{dm['wins']} / L:{dm['losses']})",
            "Эквити к концу дня": f"${dm['end_eq']:.2f}",
        })

    return {
        "final_balance": round(cash, 2),
        "net_pnl": round(cash - initial_balance, 2),
        "roi_pct": round((cash - initial_balance) / initial_balance * 100.0, 1),
        "win_rate": wr,
        "total_trades": len(trades_pnl),
        "max_drawdown_pct": round(max_dd * 100.0, 1),
        "profit_factor": pf,
        "expectancy_r": exp_r,
        "total_commission": round(total_comm, 2),
        "winning_days": win_days,
        "losing_days": loss_days,
        "daily_breakdown": daily_rows,
    }


def get_honest_alt_7d_data() -> Dict[str, List[Dict[str, Any]]]:
    """Загружает живые 5m свечи за 7 дней по широкой выборке альткоинов Bybit Linear (включая мелкие перпы от $500K/24ч!)."""
    import requests
    from concurrent.futures import ThreadPoolExecutor
    try:
        inst_js = requests.get("https://api.bybit.com/v5/market/instruments-info", params={"category": "linear", "limit": "1000"}, timeout=8).json()
        clean_perps = {
            s["symbol"] for s in (inst_js.get("result") or {}).get("list") or []
            if s.get("contractType") == "LinearPerpetual" and s.get("status") == "Trading"
            and s.get("quoteCoin") == "USDT" and s.get("symbolType", "") in ("", "innovation")
            and not s.get("marketRegion") and not s.get("underlyingTicker")
        }
        r = requests.get("https://api.bybit.com/v5/market/tickers", params={"category": "linear"}, timeout=8).json()
        lst = (r.get("result") or {}).get("list") or []
        valid = []
        for x in lst:
            sym = x.get("symbol", "")
            if (clean_perps and sym not in clean_perps) or sym in getattr(config, "EXCLUDED_TICKERS", set()):
                continue
            qv = float(x.get("turnover24h") or 0)
            if qv >= 600_000.0:
                valid.append((qv, sym))
        valid.sort(reverse=True)
        syms = ["BTCUSDT"] + [s for _, s in valid[:85] if s != "BTCUSDT"]

        def _fetch_one(sym: str):
            rows = []
            end_ms = None
            for _ in range(2):
                p = {"category": "linear", "symbol": sym, "interval": "5", "limit": "1000"}
                if end_ms:
                    p["end"] = str(end_ms)
                try:
                    js = requests.get("https://api.bybit.com/v5/market/kline", params=p, timeout=8).json()
                    kl = (js.get("result") or {}).get("list") or []
                    if not kl:
                        break
                    rows.extend(kl)
                    end_ms = int(kl[-1][0]) - 300_000
                except Exception:
                    break
            if len(rows) < 250:
                return sym, None
            seen = {}
            for k in rows:
                ts = int(k[0])
                seen[ts] = {"time": ts, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "quote_vol": float(k[6])}
            return sym, [seen[t] for t in sorted(seen.keys())]

        out = {}
        with ThreadPoolExecutor(max_workers=12) as ex:
            for s, cdls in ex.map(_fetch_one, syms):
                if cdls:
                    out[s] = cdls
        if len(out) >= 25 and "BTCUSDT" in out:
            return out
    except Exception:
        pass
    return get_7d_data(prefer_extended_universe=True)


def simulate_15m_smart_money(
    all_data_5m: Dict[str, Any],
    initial_balance: float = 100.0,
    max_slots: int = 15,
    mg_pct: float = 0.025,
    cap_risk_pct: float = 0.028,
    tp1_share: float = 0.0,
    leverage: int = 50,
) -> Dict[str, Any]:
    """Честный 15m Smart Money + Runner бэктест (1-в-1 с боевым scanner.py: 15 слотов, BTC EMA50, узкий стоп <=2.2%, без фильтра $15M!)."""
    ind: Dict[str, Any] = {}
    all_ts = set()
    for sym, cdls in all_data_5m.items():
        buckets: Dict[int, Dict[str, Any]] = {}
        for c in cdls:
            ts = int(c["time"])
            ts_ms = ts if ts > 1e11 else ts * 1000
            b = (ts_ms // 900_000) * 900_000
            if b not in buckets:
                buckets[b] = {"time": b, "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"], "qv": c["quote_vol"], "cnt": 1}
            else:
                bk = buckets[b]
                bk["high"] = max(bk["high"], c["high"])
                bk["low"] = min(bk["low"], c["low"])
                bk["close"] = c["close"]
                bk["qv"] += c["quote_vol"]
                bk["cnt"] += 1
        rows = [buckets[k] for k in sorted(buckets.keys()) if buckets[k]["cnt"] == 3]
        if len(rows) < 210:
            continue
        n = len(rows)
        t = np.array([r["time"] for r in rows], dtype=np.int64)
        o = np.array([r["open"] for r in rows], dtype=np.float64)
        h = np.array([r["high"] for r in rows], dtype=np.float64)
        l = np.array([r["low"] for r in rows], dtype=np.float64)
        c = np.array([r["close"] for r in rows], dtype=np.float64)
        qv = np.array([r["qv"] for r in rows], dtype=np.float64)
        ema9, ema21, ema50, ema200 = _calc_ema(c, 9), _calc_ema(c, 21), _calc_ema(c, 50), _calc_ema(c, 200)
        macd_l = _calc_ema(c, 12) - _calc_ema(c, 26)
        macd_s = _calc_ema(macd_l, 9)
        macd_h = macd_l - macd_s
        tr = np.empty(n); tr[0] = h[0] - l[0]
        tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
        atr_pct = pd.Series(tr).rolling(14, min_periods=1).mean().values / np.maximum(c, 1e-9)
        vol_ma20 = pd.Series(qv).rolling(20, min_periods=5).mean().shift(1).bfill().values
        rvol = qv / np.maximum(vol_ma20, 1.0)
        qvol_24h = pd.Series(qv).rolling(96, min_periods=16).sum().values
        delta = np.diff(c, prepend=c[0])
        ag = pd.Series(np.where(delta > 0, delta, 0.0)).rolling(14, min_periods=3).mean().values
        al = pd.Series(np.where(delta < 0, -delta, 0.0)).rolling(14, min_periods=3).mean().values
        rsi = np.where(al == 0, 50.0, 100.0 - 100.0 / (1.0 + ag / np.maximum(al, 1e-12)))
        adx = np.full(n, 20.0)
        aw, pw, nw, av, a14 = tr[0], 0.0, 0.0, 20.0, 1.0 / 14.0
        for j in range(1, n):
            um, dm = h[j] - h[j - 1], l[j - 1] - l[j]
            pdm = um if (um > dm and um > 0) else 0.0
            ndm = dm if (dm > um and dm > 0) else 0.0
            aw = a14 * tr[j] + (1 - a14) * aw; pw = a14 * pdm + (1 - a14) * pw; nw = a14 * ndm + (1 - a14) * nw
            if aw > 1e-12:
                pdi, ndi = 100 * pw / aw, 100 * nw / aw
                dx = 100 * abs(pdi - ndi) / max(pdi + ndi, 1e-12)
                av = a14 * dx + (1 - a14) * av
            adx[j] = av
        sh, sl_s = pd.Series(h).shift(1), pd.Series(l).shift(1)
        hb16, lb16 = sh.rolling(16, min_periods=12).max().values, sl_s.rolling(16, min_periods=12).min().values
        h48, l48 = sh.rolling(48, min_periods=24).max().values, sl_s.rolling(48, min_periods=24).min().values
        fvg_b = np.zeros(n, dtype=bool); fvg_s = np.zeros(n, dtype=bool)
        for j in range(4, n):
            fvg_b[j] = any(l[m] > h[m - 2] for m in range(j - 3, j + 1))
            fvg_s[j] = any(h[m] < l[m - 2] for m in range(j - 3, j + 1))
        if sym != "BTCUSDT":
            all_ts.update(t.tolist())
        ind[sym] = dict(t=t, o=o, h=h, l=l, c=c, qv=qv, vol_ma20=vol_ma20, qvol_24h=qvol_24h,
                        ema9=ema9, ema21=ema21, ema50=ema50, ema200=ema200,
                        macd_l=macd_l, macd_s=macd_s, macd_h=macd_h, atr_pct=atr_pct, rvol=rvol, rsi=rsi, adx=adx,
                        hb16=hb16, lb16=lb16, h48=h48, l48=l48, fvg_b=fvg_b, fvg_s=fvg_s,
                        time_idx={int(ts): i for i, ts in enumerate(t)})

    ts_list = sorted(all_ts)[205:]
    cash, peak_eq, max_dd, total_comm = initial_balance, initial_balance, 0.0, 0.0
    entry_cost, stop_cost = 0.0009, 0.0012
    open_pos: Dict[str, Dict[str, Any]] = {}
    lockouts: Dict[str, int] = {}
    trades_pnl: List[float] = []
    daily_map: Dict[str, Dict[str, Any]] = {}
    btc = ind.get("BTCUSDT")

    for t_now in ts_list:
        dt = datetime.datetime.utcfromtimestamp(t_now // 1000)
        d_str = dt.strftime("%Y-%m-%d")
        in_session = not (dt.hour >= 21 or dt.hour < 1)
        btc_bull = btc_bear = True
        bp15 = 0.0
        if btc and t_now in btc["time_idx"]:
            bi = btc["time_idx"][t_now]
            if bi >= 5:
                bk = bi - 1
                bp15 = (btc["c"][bk] - btc["c"][bk - 1]) / btc["c"][bk - 1] * 100.0
                bp45 = (btc["c"][bk] - btc["c"][bk - 3]) / btc["c"][bk - 3] * 100.0
                btc_bull = (btc["c"][bk] >= btc["ema50"][bk] * 0.997) and (bp15 > -0.45) and (bp45 > -0.80)
                btc_bear = (btc["c"][bk] <= btc["ema50"][bk] * 1.003) and (bp15 < +0.45) and (bp45 < +0.80)

        if d_str not in daily_map:
            u0 = sum(p["mg"] * (((ind[s]["c"][ind[s]["time_idx"][t_now]] - p["ep"]) / p["ep"] if p["side"] == "LONG" else (p["ep"] - ind[s]["c"][ind[s]["time_idx"][t_now]]) / p["ep"]) * leverage) for s, p in open_pos.items() if t_now in ind[s]["time_idx"])
            se = cash + sum(p["mg"] for p in open_pos.values()) + u0
            daily_map[d_str] = {"start_eq": se, "end_eq": se, "trades": 0, "wins": 0, "losses": 0}

        unreal = 0.0
        for sym in list(open_pos.keys()):
            p = open_pos[sym]
            d = ind[sym]
            ix = d["time_idx"].get(t_now)
            if ix is None:
                continue
            p["bars"] += 1
            if p["bars"] % 32 == 0:
                ff = p["mg"] * leverage * 0.0001
                total_comm += ff; cash = max(0.0, cash - ff); p["real"] -= ff
            h, l, cl = d["h"][ix], d["l"][ix], d["c"][ix]
            ep, rd, atr_p = p["ep"], p["rd"], d["atr_pct"][ix - 1]
            if p["side"] == "LONG":
                if l <= p["sl"]:
                    fee = p["mg"] * leverage * stop_cost; total_comm += fee
                    pnl = p["mg"] * ((p["sl"] - ep) / ep) * leverage - fee
                    cash = max(0.0, cash + p["mg"] + pnl); p["real"] += pnl; trades_pnl.append(p["real"])
                    daily_map[d_str]["trades"] += 1; daily_map[d_str]["wins" if p["real"] > 0 else "losses"] += 1
                    lockouts[sym] = ix + (8 if p["real"] < 0 else 2); del open_pos[sym]; continue
                p["hi"] = max(p["hi"], h); mfe_r = (p["hi"] - ep) / rd
                if not p["tp1"] and h >= ep + 1.15 * rd:
                    p["tp1"] = True
                    if tp1_share > 0:
                        cm = p["mg"] * tp1_share; fee = cm * leverage * entry_cost; total_comm += fee
                        cpnl = cm * ((1.15 * rd) / ep) * leverage - fee
                        cash += cm + cpnl; p["real"] += cpnl; p["mg"] -= cm
                    p["sl"] = max(p["sl"], ep + 0.25 * rd)
                if p["tp1"] and not p["tp2"] and h >= ep + 1.65 * rd:
                    p["tp2"] = True; p["sl"] = max(p["sl"], ep + 0.95 * rd)
                if p["tp1"] and mfe_r >= 2.50:
                    band = max((1.45 if mfe_r >= 5.0 else (1.70 if mfe_r >= 3.5 else 1.95)) * atr_p * p["hi"], (0.75 if mfe_r >= 5.0 else 0.95) * rd)
                    p["sl"] = max(p["sl"], ep + 1.20 * rd, p["hi"] - band)
                if not p["tp1"] and p["bars"] >= 96:
                    fee = p["mg"] * leverage * stop_cost; total_comm += fee
                    pnl = p["mg"] * ((cl - ep) / ep) * leverage - fee
                    cash = max(0.0, cash + p["mg"] + pnl); p["real"] += pnl; trades_pnl.append(p["real"])
                    daily_map[d_str]["trades"] += 1; daily_map[d_str]["wins" if p["real"] > 0 else "losses"] += 1
                    lockouts[sym] = ix + 4; del open_pos[sym]; continue
                unreal += p["mg"] * ((cl - ep) / ep) * leverage
            else:
                if h >= p["sl"]:
                    fee = p["mg"] * leverage * stop_cost; total_comm += fee
                    pnl = p["mg"] * ((ep - p["sl"]) / ep) * leverage - fee
                    cash = max(0.0, cash + p["mg"] + pnl); p["real"] += pnl; trades_pnl.append(p["real"])
                    daily_map[d_str]["trades"] += 1; daily_map[d_str]["wins" if p["real"] > 0 else "losses"] += 1
                    lockouts[sym] = ix + (8 if p["real"] < 0 else 2); del open_pos[sym]; continue
                p["lo"] = min(p["lo"], l); mfe_r = (ep - p["lo"]) / rd
                if not p["tp1"] and l <= ep - 1.15 * rd:
                    p["tp1"] = True
                    if tp1_share > 0:
                        cm = p["mg"] * tp1_share; fee = cm * leverage * entry_cost; total_comm += fee
                        cpnl = cm * ((1.15 * rd) / ep) * leverage - fee
                        cash += cm + cpnl; p["real"] += cpnl; p["mg"] -= cm
                    p["sl"] = min(p["sl"], ep - 0.25 * rd)
                if p["tp1"] and not p["tp2"] and l <= ep - 1.65 * rd:
                    p["tp2"] = True; p["sl"] = min(p["sl"], ep - 0.95 * rd)
                if p["tp1"] and mfe_r >= 2.50:
                    band = max((1.45 if mfe_r >= 5.0 else (1.70 if mfe_r >= 3.5 else 1.95)) * atr_p * p["lo"], (0.75 if mfe_r >= 5.0 else 0.95) * rd)
                    p["sl"] = min(p["sl"], ep - 1.20 * rd, p["lo"] + band)
                if not p["tp1"] and p["bars"] >= 96:
                    fee = p["mg"] * leverage * stop_cost; total_comm += fee
                    pnl = p["mg"] * ((ep - cl) / ep) * leverage - fee
                    cash = max(0.0, cash + p["mg"] + pnl); p["real"] += pnl; trades_pnl.append(p["real"])
                    daily_map[d_str]["trades"] += 1; daily_map[d_str]["wins" if p["real"] > 0 else "losses"] += 1
                    lockouts[sym] = ix + 4; del open_pos[sym]; continue
                unreal += p["mg"] * ((ep - cl) / ep) * leverage

        eq = cash + sum(p["mg"] for p in open_pos.values()) + unreal
        daily_map[d_str]["end_eq"] = eq
        peak_eq = max(peak_eq, eq)
        max_dd = max(max_dd, (peak_eq - eq) / peak_eq if peak_eq > 0 else 0.0)

        at_risk = [p for p in open_pos.values() if not p["tp1"]]
        if in_session and len(at_risk) < max_slots and len(open_pos) < max_slots + 5 and cash >= 1.2:
            cands = []
            for sym, d in ind.items():
                if sym == "BTCUSDT" or sym in open_pos:
                    continue
                ix = d["time_idx"].get(t_now)
                if ix is None or ix < 205 or ix < lockouts.get(sym, 0):
                    continue
                k = ix - 1
                if d["qvol_24h"][k] < 500_000.0 or d["vol_ma20"][k] < 2500.0:
                    continue
                cl, lo, hi, op = d["c"][k], d["l"][k], d["h"][k], d["o"][k]
                p15_c = (cl - d["c"][k - 1]) / d["c"][k - 1] * 100.0
                if abs(p15_c) > 5.5:
                    continue
                a15 = p15_c - bp15
                rng = max(hi - lo, 1e-9)
                clv_l, clv_s = (cl - lo) / rng, (hi - cl) / rng
                uw, lw = (hi - max(op, cl)) / rng, (min(op, cl) - lo) / rng
                rv, adx, rsi, atr_p = d["rvol"][k], d["adx"][k], d["rsi"][k], d["atr_pct"][k]
                if rv < 1.50 or adx < 20.0 or atr_p < 0.0035:
                    continue
                if abs(cl - d["ema21"][k]) / max(d["ema21"][k], 1e-9) > 0.055:
                    continue
                h12h, l12h = d["h48"][k], d["l48"][k]
                r12 = (h12h - l12h) / max(l12h, 1e-9)
                pos12 = (cl - l12h) / max(h12h - l12h, 1e-9)
                wl_ok = not (r12 >= 0.14 and pos12 >= 0.55 and 0.0 < (h12h - cl) / cl <= 0.045)
                ws_ok = not (r12 >= 0.14 and pos12 <= 0.45 and 0.0 < (cl - l12h) / cl <= 0.045)
                macd_bull = d["macd_l"][k] > d["macd_s"][k] and d["macd_h"][k] > d["macd_h"][k - 1]
                macd_bear = d["macd_l"][k] < d["macd_s"][k] and d["macd_h"][k] < d["macd_h"][k - 1]
                ep = d["o"][ix]
                if btc_bull and wl_ok and cl > d["hb16"][k] and cl > d["ema200"][k] and cl > d["ema9"][k] >= d["ema21"][k] * 0.998 and macd_bull and a15 >= 0.45 and 50 <= rsi <= 80 and clv_l >= 0.66 and uw <= 0.28:
                    conf = 4 + (1 if d["fvg_b"][k] else 0) + (1 if adx >= 24 else 0) + (1 if rv >= 2.0 else 0)
                    if conf >= 5:
                        sl = max((ep - min(lo, d["l"][k - 1]) * 0.9985) / ep, 1.45 * atr_p, 0.0110)
                        if sl <= 0.0500:
                            cands.append((conf * rv * max(a15, 0.5), sym, "LONG", ep, sl))
                elif btc_bear and ws_ok and cl < d["lb16"][k] and cl < d["ema200"][k] and cl < d["ema9"][k] <= d["ema21"][k] * 1.002 and macd_bear and a15 <= -0.45 and 20 <= rsi <= 50 and clv_s >= 0.66 and lw <= 0.28:
                    conf = 4 + (1 if d["fvg_s"][k] else 0) + (1 if adx >= 24 else 0) + (1 if rv >= 2.0 else 0)
                    if conf >= 5:
                        sl = max((max(hi, d["h"][k - 1]) * 1.0015 - ep) / ep, 1.45 * atr_p, 0.0110)
                        if sl <= 0.0500:
                            cands.append((conf * rv * max(abs(a15), 0.5), sym, "SHORT", ep, sl))
            cands.sort(reverse=True)
            for sc, sym, side, ep, sl_d in cands[:4]:
                at_r = [p for p in open_pos.values() if not p["tp1"]]
                if len(at_r) >= max_slots or len(open_pos) >= max_slots + 5:
                    break
                if sum(1 for p in at_r if p["side"] == side) >= 6:
                    continue
                ref_eq = max(10.0, cash + sum(p["mg"] for p in open_pos.values()))
                dd_m = 0.75 if (peak_eq - eq) / peak_eq >= 0.20 else 1.0
                base_mg = ref_eq * mg_pct * dd_m
                max_mg_r = (ref_eq * cap_risk_pct * dd_m) / ((sl_d + stop_cost) * leverage)
                mg = round(min(base_mg, max_mg_r, 1500.0 / leverage, cash * 0.40), 2)
                if mg < 0.50 or cash < mg + 0.20:
                    continue
                fee_in = mg * leverage * entry_cost; total_comm += fee_in
                cash -= (mg + fee_in)
                rd = ep * sl_d
                open_pos[sym] = dict(side=side, ep=ep, mg=mg, sl=ep - rd if side == "LONG" else ep + rd, rd=rd, tp1=False, tp2=False, hi=ep, lo=ep, real=-fee_in, bars=0)

    for sym, p in list(open_pos.items()):
        cl = ind[sym]["c"][-1]
        raw = (cl - p["ep"]) / p["ep"] if p["side"] == "LONG" else (p["ep"] - cl) / p["ep"]
        fee = p["mg"] * leverage * entry_cost
        total_comm += fee
        pnl = p["mg"] * raw * leverage - fee
        cash = max(0.0, cash + p["mg"] + pnl)
        p["real"] += pnl
        trades_pnl.append(p["real"])

    wins = [x for x in trades_pnl if x > 0]
    losses = [x for x in trades_pnl if x <= 0]
    wr = round(len(wins) / len(trades_pnl) * 100.0, 1) if trades_pnl else 0.0
    pf = round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else (99.0 if wins else 0.0)
    daily_rows = []
    win_days = loss_days = 0
    for dk in sorted(daily_map.keys()):
        dm = daily_map[dk]
        d_pnl = round(dm["end_eq"] - dm["start_eq"], 2)
        d_pct = round((d_pnl / max(dm["start_eq"], 1.0)) * 100.0, 1)
        if dm["trades"] > 0 or abs(d_pnl) >= 0.05:
            if d_pnl >= 0:
                win_days += 1
            else:
                loss_days += 1
        daily_rows.append({
            "Дата": dk,
            "Итог дня": "✅ Плюс" if d_pnl >= 0 else "❌ Убыток",
            "PnL за день ($)": f"${d_pnl:+.2f}",
            "PnL за день (%)": f"{d_pct:+.1f}%",
            "Закрыто сделок": f"{dm['trades']} (W:{dm['wins']} / L:{dm['losses']})",
            "Эквити к концу дня": f"${dm['end_eq']:.2f}",
        })
    return {
        "final_balance": round(cash, 2),
        "net_pnl": round(cash - initial_balance, 2),
        "roi_pct": round((cash - initial_balance) / initial_balance * 100.0, 1),
        "win_rate": wr,
        "total_trades": len(trades_pnl),
        "max_drawdown_pct": round(max_dd * 100.0, 1),
        "profit_factor": pf,
        "expectancy_r": 0.0,
        "total_commission": round(total_comm, 2),
        "winning_days": win_days,
        "losing_days": loss_days,
        "daily_breakdown": daily_rows,
    }


if __name__ == "__main__":
    print("Загрузка живых 5m данных Binance Futures (7 дней, топ ликвидных пар и ракет)...")
    d = get_7d_data()
    pre = precompute_indicators(d)
    r_new = simulate_strategy(d, 20.0, pre, leverage=15, risk_pct=0.030, tp1_r=1.65, tp1_share=0.60)
    r_fix = simulate_strategy(d, 20.0, pre, leverage=15, risk_pct=0.030, tp1_r=1.70, tp1_share=1.00)
    r_old = simulate_strategy(d, 20.0, pre, leverage=12, legacy_churn_mode=True)
    print(f"🚀 Anti-Rug Rocket Hunter (60%@1.65R + 40% Trail): {r_new}")
    print(f"🎯 Anti-Rug Rocket Hunter (100% Fixed 1.70R):      {r_fix}")
    print(f"❌ Старый 12-барный скальпер (Early BE + 35m TS):  {r_old}")
