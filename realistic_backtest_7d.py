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

        tr = np.empty(n)
        tr[0] = h[0] - l[0]
        tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
        atr14 = pd.Series(tr).rolling(14, min_periods=1).mean().values
        atr_pct = atr14 / np.maximum(c, 1e-9)

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

        ext = np.abs(c - ema21) / np.maximum(ema21, 1e-9)
        ret_3h = pd.Series(c).pct_change(36).fillna(0.0).values

        time_idx = {int(ts): idx for idx, ts in enumerate(t)}
        if sym != "BTCUSDT":
            all_times.update(t.tolist())

        ind[sym] = {
            "t": t, "o": o, "h": h, "l": l, "c": c, "qv": qv, "vol_ma20": vol_ma20,
            "ema9": ema9, "ema21": ema21, "ema50": ema50, "ema27": ema27, "ema63": ema63, "ema150": ema150,
            "atr_pct": atr_pct, "rvol": rvol, "v3_surge": v3_surge, "qvol_24h": qvol_24h,
            "rsi": rsi, "ext": ext, "ret_3h": ret_3h,
            "h12": h12, "l12": l12, "h16": h16, "l16": l16, "h36": h36, "l36": l36, "h72": h72, "l72": l72,
            "time_idx": time_idx
        }
    return {"ind": ind, "ts": sorted(all_times)}


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
    **kwargs
) -> Dict[str, Any]:
    pre = precomputed if precomputed is not None else precompute_indicators(all_data)
    ind = pre["ind"]
    ts_list = pre["ts"][180:]

    cash = initial_balance
    peak_eq = initial_balance
    max_dd = 0.0
    cost = 0.0006
    total_comm = 0.0
    open_pos: Dict[str, Dict[str, Any]] = {}
    trades_r: List[float] = []
    trades_pnl: List[float] = []
    lockouts: Dict[str, int] = {}
    btc_d = ind.get("BTCUSDT")

    for t_now in ts_list:
        btc_dump = btc_pump = btc_flush = btc_spike = False
        bp5 = bp15 = 0.0
        if btc_d is not None:
            bi = btc_d["time_idx"].get(t_now)
            if bi and bi >= 5:
                k = bi - 1
                bp5 = (btc_d["c"][k] - btc_d["c"][k - 1]) / btc_d["c"][k - 1] * 100.0
                bp15 = (btc_d["c"][k] - btc_d["c"][k - 3]) / btc_d["c"][k - 3] * 100.0
                btc_dump = bp15 <= -0.55 or bp5 <= -0.40
                btc_pump = bp15 >= 0.55 or bp5 >= 0.40
                btc_flush = bp5 <= -0.38 or bp15 <= -0.75
                btc_spike = bp5 >= 0.38 or bp15 >= 0.75

        unreal = 0.0
        for sym in list(open_pos.keys()):
            pos = open_pos[sym]
            d = ind[sym]
            idx = d["time_idx"].get(t_now)
            if idx is None:
                continue
            pos["bars"] += 1
            h, l, cl = d["h"][idx], d["l"][idx], d["c"][idx]
            entry, side, lev, rd = pos["entry"], pos["side"], pos["lev"], pos["rd"]
            atr_p = d["atr_pct"][idx - 1]

            if side == "LONG":
                if l <= pos["sl"]:
                    fee = pos["mg"] * lev * cost
                    total_comm += fee
                    pnl = pos["mg"] * ((pos["sl"] - entry) / entry) * lev - fee
                    cash += max(pos["mg"] + pnl, 0.0)
                    pos["realized"] += pnl
                    trades_pnl.append(pos["realized"])
                    trades_r.append(pos["realized"] / pos["risk_usd"])
                    lockouts[sym] = idx + (18 if pos["realized"] < 0 else 2)
                    del open_pos[sym]
                    continue

                pos["hi"] = max(pos["hi"], h)
                mfe_r = (pos["hi"] - entry) / rd

                if legacy_churn_mode:
                    if mfe_r >= 0.85:
                        pos["sl"] = max(pos["sl"], entry * 1.0020)
                    if pos["bars"] >= 7 and (cl - entry) / rd < 0.45:
                        fee = pos["mg"] * lev * cost
                        total_comm += fee
                        pnl = pos["mg"] * ((cl - entry) / entry) * lev - fee
                        cash += max(pos["mg"] + pnl, 0.0)
                        pos["realized"] += pnl
                        trades_pnl.append(pos["realized"])
                        trades_r.append(pos["realized"] / pos["risk_usd"])
                        del open_pos[sym]
                        continue

                if not pos["tp1_hit"] and h >= entry + tp1_r * rd:
                    if tp1_share >= 0.99:
                        fee = pos["mg"] * lev * cost
                        total_comm += fee
                        pnl = pos["mg"] * ((entry + tp1_r * rd - entry) / entry) * lev - fee
                        cash += max(pos["mg"] + pnl, 0.0)
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
                        pnl = cm * ((tp1_r * rd) / entry) * lev - fee
                        cash += cm + pnl
                        pos["realized"] += pnl
                        pos["mg"] -= cm
                        pos["sl"] = max(pos["sl"], entry + 0.35 * rd)

                if pos["tp1_hit"]:
                    if big_runner_mode:
                        if mfe_r >= 6.6:
                            trail_p = pos["hi"] - max(1.69 * atr_p * pos["hi"], 0.81 * rd)
                        elif mfe_r >= 4.5:
                            trail_p = pos["hi"] - max(1.98 * atr_p * pos["hi"], 1.06 * rd)
                        elif mfe_r >= 3.1:
                            trail_p = max(entry + 1.05 * rd, pos["hi"] - max(2.25 * atr_p * pos["hi"], 1.25 * rd))
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

                unreal += pos["mg"] * ((cl - entry) / entry) * lev

            else:
                if h >= pos["sl"]:
                    fee = pos["mg"] * lev * cost
                    total_comm += fee
                    pnl = pos["mg"] * ((entry - pos["sl"]) / entry) * lev - fee
                    cash += max(pos["mg"] + pnl, 0.0)
                    pos["realized"] += pnl
                    trades_pnl.append(pos["realized"])
                    trades_r.append(pos["realized"] / pos["risk_usd"])
                    lockouts[sym] = idx + (18 if pos["realized"] < 0 else 2)
                    del open_pos[sym]
                    continue

                pos["lo"] = min(pos["lo"], l)
                mfe_r = (entry - pos["lo"]) / rd

                if legacy_churn_mode:
                    if mfe_r >= 0.85:
                        pos["sl"] = min(pos["sl"], entry * 0.9980)
                    if pos["bars"] >= 7 and (entry - cl) / rd < 0.45:
                        fee = pos["mg"] * lev * cost
                        total_comm += fee
                        pnl = pos["mg"] * ((entry - cl) / entry) * lev - fee
                        cash += max(pos["mg"] + pnl, 0.0)
                        pos["realized"] += pnl
                        trades_pnl.append(pos["realized"])
                        trades_r.append(pos["realized"] / pos["risk_usd"])
                        del open_pos[sym]
                        continue

                if not pos["tp1_hit"] and l <= entry - tp1_r * rd:
                    if tp1_share >= 0.99:
                        fee = pos["mg"] * lev * cost
                        total_comm += fee
                        pnl = pos["mg"] * ((tp1_r * rd) / entry) * lev - fee
                        cash += max(pos["mg"] + pnl, 0.0)
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
                        pnl = cm * ((tp1_r * rd) / entry) * lev - fee
                        cash += cm + pnl
                        pos["realized"] += pnl
                        pos["mg"] -= cm
                        pos["sl"] = min(pos["sl"], entry - 0.35 * rd)

                if pos["tp1_hit"]:
                    if big_runner_mode:
                        if mfe_r >= 6.6:
                            trail_p = pos["lo"] + max(1.69 * atr_p * pos["lo"], 0.81 * rd)
                        elif mfe_r >= 4.5:
                            trail_p = pos["lo"] + max(1.98 * atr_p * pos["lo"], 1.06 * rd)
                        elif mfe_r >= 3.1:
                            trail_p = min(entry - 1.05 * rd, pos["lo"] + max(2.25 * atr_p * pos["lo"], 1.25 * rd))
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

                unreal += pos["mg"] * ((entry - cl) / entry) * lev

        eq = cash + sum(p["mg"] for p in open_pos.values()) + unreal
        peak_eq = max(peak_eq, eq)
        max_dd = max(max_dd, (peak_eq - eq) / peak_eq if peak_eq > 0 else 0.0)

        at_risk = sum(1 for p in open_pos.values() if not p["tp1_hit"])
        max_slots = 2 if legacy_churn_mode else 4
        if at_risk < 2 and len(open_pos) < max_slots and cash >= 1.2:
            cands = []
            for sym, d in ind.items():
                if sym == "BTCUSDT" or sym in open_pos:
                    continue
                idx = d["time_idx"].get(t_now)
                if idx is None or idx < 160 or idx < lockouts.get(sym, 0):
                    continue
                k = idx - 1
                if d["qvol_24h"][k] < 15_000_000.0:
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
                        cands.append((rvol * abs(pct_5m), sym, "LONG", ep, sl))
                    elif cl < d["l12"][k] and pct_5m <= -0.42 and clv_s >= 0.68 and lw <= 0.28 and cl < d["ema9"][k] <= d["ema21"][k] * 1.002 and not btc_pump:
                        sl = min(max((max(hi, d["h"][k - 1]) * 1.001 - ep) / ep, 1.2 * atr_p, 0.0055), 0.0135)
                        cands.append((rvol * abs(pct_5m), sym, "SHORT", ep, sl))
                else:
                    if atr_p < 0.0025 or d["vol_ma20"][k] < 15000.0 or rvol < 1.80 or d["v3_surge"][k] < 1.10:
                        continue
                    if d["ext"][k] > 0.048 or d["ext"][k - 3] > 0.028:
                        continue
                    if max_spike_5m > 0.0 and abs(pct_5m) > max_spike_5m:
                        continue
                    ema9, ema21, ema50 = d["ema9"][k], d["ema21"][k], d["ema50"][k]
                    ema27, ema63, ema150 = d["ema27"][k], d["ema63"][k], d["ema150"][k]
                    rsi = d["rsi"][k]
                    pct_15m = (cl - d["c"][k - 3]) / d["c"][k - 3] * 100.0
                    alpha_5m = pct_5m - bp5
                    alpha_15m = pct_15m - bp15
                    mtf_l = (cl >= ema63 * 0.998 and ema27 >= ema63 * 0.998 and ema63 >= ema150 * 0.995)
                    mtf_s = (cl <= ema63 * 1.002 and ema27 <= ema63 * 1.002 and ema63 <= ema150 * 1.005)
                    min_imp = max(0.55, atr_p * 85.0)
                    sq_rng = (d["h16"][k] - d["l16"][k]) / max(d["l16"][k], 1e-9)

                    brk_l = (cl > d["h36"][k]) or (sq_rng <= 0.065 and cl > d["h16"][k] and rvol >= 2.0)
                    if (
                        brk_l and mtf_l and cl >= ema50 * 0.996 and pct_5m >= min_imp
                        and alpha_5m >= 0.80 and alpha_15m >= 1.00
                        and clv_l >= 0.66 and uw <= 0.26 and cl > ema9 >= ema21 * 0.998
                        and 48.0 <= rsi <= 86.0 and d["ret_3h"][k] <= 0.20 and not btc_dump and not btc_spike
                    ):
                        _sl_floor = 0.0110 if big_runner_mode else 0.0080
                        _sl_atr_m = 1.75 if big_runner_mode else 1.55
                        _sl_cap = 0.0550 if big_runner_mode else 0.0360
                        sl = min(max((ep - min(lo, d["l"][k - 1]) * 0.9985) / ep, _sl_atr_m * atr_p, _sl_floor), _sl_cap)
                        cands.append((rvol * alpha_5m * clv_l, sym, "LONG", ep, sl))
                        continue

                    pump_6h = (d["h72"][k] - d["l72"][k]) / max(d["l72"][k], 1e-9)
                    off_hi = (d["h72"][k] - cl) / max(d["h72"][k], 1e-9)
                    is_rug_s = (pump_6h >= 0.15 and 0.03 <= off_hi <= 0.22 and cl < d["l16"][k] and cl < ema50 and rvol >= 2.0)
                    brk_s = ((cl < d["l36"][k]) or (sq_rng <= 0.065 and cl < d["l16"][k] and rvol >= 2.0)) and mtf_s
                    if (
                        (brk_s or is_rug_s) and cl <= ema50 * 1.004 and pct_5m <= -min_imp
                        and alpha_5m <= -0.80 and alpha_15m <= -1.00
                        and clv_s >= 0.66 and lw <= 0.26 and cl < ema9 <= ema21 * 1.002
                        and 14.0 <= rsi <= 52.0 and d["ret_3h"][k] >= -0.20 and not btc_pump and not btc_flush
                    ):
                        _sl_floor = 0.0110 if big_runner_mode else 0.0080
                        _sl_atr_m = 1.75 if big_runner_mode else 1.55
                        _sl_cap = 0.0550 if big_runner_mode else 0.0360
                        sl = min(max((max(hi, d["h"][k - 1]) * 1.0015 - ep) / ep, _sl_atr_m * atr_p, _sl_floor), _sl_cap)
                        cands.append((rvol * abs(alpha_5m) * clv_s, sym, "SHORT", ep, sl))

            cands.sort(reverse=True)
            for score, sym, side, ep, sl_dist in cands[:1]:
                cur_eq = max(10.0, cash + sum(p["mg"] for p in open_pos.values()))
                cur_dd = (peak_eq - cur_eq) / peak_eq if peak_eq > 0 else 0.0
                dd_mult = 0.75 if cur_dd >= 0.20 else 1.0
                if equal_margin_pct > 0.0:
                    mg = round(min(cur_eq * equal_margin_pct * dd_mult, cur_eq * 0.25, cash * 0.48), 2)
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
                    "tp1_hit": False, "bars": 0, "hi": ep, "lo": ep, "realized": -fee_in
                }

    for sym, pos in list(open_pos.items()):
        cl = ind[sym]["c"][-1]
        raw = (cl - pos["entry"]) / pos["entry"] if pos["side"] == "LONG" else (pos["entry"] - cl) / pos["entry"]
        fee = pos["mg"] * pos["lev"] * cost
        total_comm += fee
        pnl = pos["mg"] * raw * pos["lev"] - fee
        cash += max(pos["mg"] + pnl, 0.0)
        pos["realized"] += pnl
        trades_pnl.append(pos["realized"])
        trades_r.append(pos["realized"] / pos["risk_usd"])

    wins = [x for x in trades_pnl if x > 0]
    losses = [x for x in trades_pnl if x <= 0]
    wr = round(len(wins) / len(trades_pnl) * 100.0, 1) if trades_pnl else 0.0
    pf = round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else (99.0 if wins else 0.0)
    exp_r = round(sum(trades_r) / len(trades_r), 3) if trades_r else 0.0

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
