import os
import glob
import json
import time
import requests
import pandas as pd
from typing import List, Dict, Any, Optional
import config
from quant_features import compute_quant_features_dataframe, FEATURE_COLS_LONG, FEATURE_COLS_SHORT
from ml_engine import ml_engine

SYMBOLS = [
    "SUIUSDT", "PEPEUSDT", "DOGEUSDT", "NEARUSDT", "SOLUSDT",
    "ENAUSDT", "JUPUSDT", "RENDERUSDT", "WIFUSDT", "APTUSDT",
    "TIAUSDT", "SEIUSDT"
]
CACHE_FILE = "candles_cache_7d.json"
ML_CACHE_DIR = ".cache_ml_candles"


def get_7d_data(prefer_extended_universe: bool = True) -> Dict[str, List[Dict[str, float]]]:
    """
    Загружает исторические 5m свечи.
    Если доступен расширенный кэш из 26 пар (.cache_ml_candles, ~76 000 свечей включая BTCUSDT),
    использует его для максимально достоверной проверки без подгонки. Иначе берет candles_cache_7d.json или скачивает с Binance Vision.
    """
    if prefer_extended_universe and os.path.isdir(ML_CACHE_DIR):
        files = sorted(glob.glob(os.path.join(ML_CACHE_DIR, "*_5m.json")))
        if len(files) >= 12:
            ext_data: Dict[str, List[Dict[str, float]]] = {}
            for p in files:
                sym = os.path.basename(p).replace("_5m.json", "")
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if not raw:
                        continue
                    cdls = []
                    for c in raw:
                        if isinstance(c, list):
                            cdls.append({
                                "time": int(c[0]), "open": float(c[1]), "high": float(c[2]),
                                "low": float(c[3]), "close": float(c[4]), "volume": float(c[5]),
                                "quote_vol": float(c[7])
                            })
                        else:
                            qv = c.get("quote_vol")
                            if qv is None:
                                qv = float(c.get("volume", 0.0)) * float(c.get("close", 1.0))
                            cdls.append({**c, "quote_vol": float(qv)})
                    if len(cdls) >= 500:
                        ext_data[sym] = cdls
                except Exception:
                    continue
            if len(ext_data) >= 12:
                return ext_data

    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (7 * 24 * 60 * 60 * 1000)
    data = {}

    for s in SYMBOLS + ["BTCUSDT"]:
        cdls = []
        cur_start = start_ms
        while cur_start < now_ms:
            url = "https://data-api.binance.vision/api/v3/klines"
            params = {"symbol": s, "interval": "5m", "startTime": cur_start, "limit": 1000}
            try:
                r = requests.get(url, params=params, timeout=8)
                if r.status_code != 200:
                    break
                chunk = r.json()
                if not chunk or not isinstance(chunk, list):
                    break
                for c in chunk:
                    cdls.append({
                        "time": int(c[0]),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                        "quote_vol": float(c[7])
                    })
                cur_start = chunk[-1][0] + (5 * 60 * 1000)
                if len(chunk) < 1000:
                    break
            except Exception:
                break
        if len(cdls) >= 1000:
            data[s] = cdls

    if data:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    return data


def _calc_ema_series(closes: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1.0)
    out = [closes[0]]
    ema = closes[0]
    for v in closes[1:]:
        ema = v * k + ema * (1.0 - k)
        out.append(ema)
    return out


def _calc_rsi_series(closes: List[float], period: int = 14) -> List[float]:
    out = [50.0] * len(closes)
    if len(closes) <= period:
        return out
    gains = [0.0] * len(closes)
    losses = [0.0] * len(closes)
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains[i] = d
        else:
            losses[i] = -d
    for i in range(period, len(closes)):
        ag = sum(gains[i - period + 1: i + 1]) / period
        al = sum(losses[i - period + 1: i + 1]) / period
        out[i] = (100.0 if ag > 0 else 50.0) if al == 0 else (100.0 - (100.0 / (1.0 + ag / al)))
    return out


def _calc_atr_series(cdls: List[Dict[str, float]], period: int = 14) -> List[float]:
    trs = [cdls[0]["high"] - cdls[0]["low"]]
    for i in range(1, len(cdls)):
        c, p = cdls[i], cdls[i - 1]
        trs.append(max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"])))
    return [sum(trs[max(0, i - period + 1): i + 1]) / len(trs[max(0, i - period + 1): i + 1]) for i in range(len(cdls))]


def precompute_indicators(all_data: Dict[str, List[Dict[str, float]]]) -> Dict[str, Dict[str, Any]]:
    """Предрасчет индикаторов и ML-вероятностей без заглядывания в будущее."""
    ind: Dict[str, Dict[str, Any]] = {}
    has_ml = (ml_engine.model_long is not None and ml_engine.model_short is not None)
    for sym, cdls in all_data.items():
        if not cdls:
            continue
        closes = [c["close"] for c in cdls]
        entry: Dict[str, Any] = {
            "ema9": _calc_ema_series(closes, 9),
            "ema21": _calc_ema_series(closes, 21),
            "rsi": _calc_rsi_series(closes, 14),
            "atr": _calc_atr_series(cdls, 14),
            "time_idx": {c["time"]: i for i, c in enumerate(cdls)},
            "ml_long": [0.55] * len(cdls),
            "ml_short": [0.55] * len(cdls),
        }
        if sym != "BTCUSDT" and has_ml and len(cdls) >= 30:
            try:
                df = pd.DataFrame(cdls)
                fdf = compute_quant_features_dataframe(df)
                if not fdf.empty:
                    xl = fdf[FEATURE_COLS_LONG].fillna(0.0).values
                    xs = fdf[FEATURE_COLS_SHORT].fillna(0.0).values
                    entry["ml_long"] = ml_engine.model_long.predict_proba(xl)[:, 1].tolist()
                    entry["ml_short"] = ml_engine.model_short.predict_proba(xs)[:, 1].tolist()
            except Exception:
                pass
        ind[sym] = entry
    return ind


def simulate_strategy(
    all_data: Dict[str, List[Dict[str, float]]],
    leverage: int = 12,
    risk_pct: float = 0.025,
    lookback: int = 20,
    min_surge: float = 1.80,
    min_impulse: float = 0.60,
    min_clv: float = 0.68,
    max_wick_exh: float = 0.28,
    ml_min_prob: float = 0.42,
    tp1_r: float = 1.5,
    tp2_r: float = 3.0,
    atr_trail_mult: float = 2.5,
    time_stop_bars: int = 7,
    legacy_churn_mode: bool = False,
    initial_balance: float = 20.0,
    precomputed: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    100% ЧЕСТНЫЙ ИНСТИТУЦИОНАЛЬНЫЙ БЭКТЕСТ (БЕЗ LOOKAHEAD BIAS И ИЛЛЮЗИЙ):
      - Сигнал вычисляется на закрытой свече [idx - 1], вход по цене открытия следующей свечи [idx]["open"].
      - Учтены реальные комиссии тейкера (0.05%) + проскальзывание (0.01%) на КАЖДУЮ сторону (= 0.12% на круг).
      - Консервативный порядок внутри свечи: сначала проверяется Stop-Loss, и только потом Take-Profit.
      - Строгий учет: 1 открытая позиция = 1 сделка в статистике (частичные тейки агрегируются в общий PnL позиции).
    """
    ind = precomputed if precomputed is not None else precompute_indicators(all_data)
    all_ts = sorted({c["time"] for sym, cdls in all_data.items() if sym != "BTCUSDT" for c in cdls})

    cash = initial_balance
    peak_eq = initial_balance
    max_dd = 0.0
    total_commission = 0.0
    rt_cost_per_side = 0.0006  # 0.05% биржевая комиссия тейкера + 0.01% проскальзывание на каждую сторону

    open_pos: Dict[str, Dict[str, Any]] = {}
    trades: List[Dict[str, Any]] = []
    r_mults: List[float] = []
    lockouts: Dict[str, int] = {}
    daily_losses = 0
    cur_day = None

    for t_now in all_ts[45:]:
        day_s = time.strftime("%Y-%m-%d", time.gmtime(t_now / 1000))
        if day_s != cur_day:
            cur_day = day_s
            daily_losses = 0

        btc_dump, btc_pump = False, False
        if "BTCUSDT" in ind:
            b_idx = ind["BTCUSDT"]["time_idx"].get(t_now)
            if b_idx and b_idx >= 5:
                bc = all_data["BTCUSDT"]
                bp5 = (bc[b_idx - 1]["close"] - bc[b_idx - 2]["close"]) / bc[b_idx - 2]["close"] * 100.0
                bp15 = (bc[b_idx - 1]["close"] - bc[b_idx - 4]["close"]) / bc[b_idx - 4]["close"] * 100.0
                btc_dump = bp15 <= -0.45 or bp5 <= -0.35
                btc_pump = bp15 >= 0.45 or bp5 >= 0.35

        # 1. СОПРОВОЖДЕНИЕ ОТКРЫТЫХ ПОЗИЦИЙ
        unreal = 0.0
        for sym in list(open_pos.keys()):
            pos = open_pos[sym]
            idx = ind[sym]["time_idx"].get(t_now)
            if idx is None:
                continue
            c = all_data[sym][idx]
            pos["bars_held"] += 1
            entry, side, lev = pos["entry"], pos["side"], pos["lev"]
            h, l, cl = c["high"], c["low"], c["close"]
            atr_pct = ind[sym]["atr"][idx - 1] / entry

            tp1_share = 0.50 if legacy_churn_mode else 0.30
            tp2_rem_share = 0.50 if legacy_churn_mode else (0.30 / 0.70)

            if side == "LONG":
                if l <= pos["sl"]:
                    xp = pos["sl"]
                    fee = pos["margin"] * lev * rt_cost_per_side
                    total_commission += fee
                    pnl = pos["margin"] * ((xp - entry) / entry) * lev - fee
                    cash += max(pos["margin"] + pnl, 0.0)
                    pos["realized"] += pnl
                    trades.append({"sym": sym, "side": side, "pnl": pos["realized"]})
                    r_mults.append(pos["realized"] / pos["risk_usd"])
                    if pos["realized"] <= -0.12:
                        daily_losses += 1
                        lockouts[sym] = t_now + 45 * 60 * 1000
                    del open_pos[sym]
                    continue

                if not pos["tp1_hit"] and h >= pos["tp1"]:
                    pos["tp1_hit"] = True
                    cm = pos["init_margin"] * tp1_share
                    fee = cm * lev * rt_cost_per_side
                    total_commission += fee
                    pnl = cm * ((pos["tp1"] - entry) / entry) * lev - fee
                    cash += cm + pnl
                    pos["realized"] += pnl
                    pos["margin"] -= cm
                    pos["sl"] = max(pos["sl"], entry * 1.0020)

                if pos["tp1_hit"] and not pos["tp2_hit"] and h >= pos["tp2"]:
                    pos["tp2_hit"] = True
                    cm = pos["margin"] * tp2_rem_share
                    fee = cm * lev * rt_cost_per_side
                    total_commission += fee
                    pnl = cm * ((pos["tp2"] - entry) / entry) * lev - fee
                    cash += cm + pnl
                    pos["realized"] += pnl
                    pos["margin"] -= cm
                    if not legacy_churn_mode:
                        pos["sl"] = max(pos["sl"], entry + 1.2 * pos["risk_dist"])

                pos["highest"] = max(pos["highest"], h)
                if legacy_churn_mode and pos["tp1_hit"]:
                    trail_p = pos["highest"] * (1.0 - 0.007)
                    if trail_p > pos["sl"]:
                        pos["sl"] = trail_p
                elif pos["tp1_hit"] and (pos["tp2_hit"] or pos["highest"] >= entry + 2.2 * pos["risk_dist"]):
                    trail_p = pos["highest"] * (1.0 - max(atr_pct * atr_trail_mult, 0.013))
                    if trail_p > pos["sl"]:
                        pos["sl"] = trail_p

                if not legacy_churn_mode and not pos["tp1_hit"] and pos["bars_held"] >= time_stop_bars:
                    if (cl - entry) / pos["risk_dist"] < 0.45:
                        fee = pos["margin"] * lev * rt_cost_per_side
                        total_commission += fee
                        pnl = pos["margin"] * ((cl - entry) / entry) * lev - fee
                        cash += max(pos["margin"] + pnl, 0.0)
                        pos["realized"] += pnl
                        trades.append({"sym": sym, "side": side, "pnl": pos["realized"]})
                        r_mults.append(pos["realized"] / pos["risk_usd"])
                        if pos["realized"] <= -0.15:
                            daily_losses += 1
                        lockouts[sym] = t_now + 20 * 60 * 1000
                        del open_pos[sym]
                        continue

                unreal += pos["margin"] * ((cl - entry) / entry) * lev

            else:  # SHORT
                if h >= pos["sl"]:
                    xp = pos["sl"]
                    fee = pos["margin"] * lev * rt_cost_per_side
                    total_commission += fee
                    pnl = pos["margin"] * ((entry - xp) / entry) * lev - fee
                    cash += max(pos["margin"] + pnl, 0.0)
                    pos["realized"] += pnl
                    trades.append({"sym": sym, "side": side, "pnl": pos["realized"]})
                    r_mults.append(pos["realized"] / pos["risk_usd"])
                    if pos["realized"] <= -0.12:
                        daily_losses += 1
                        lockouts[sym] = t_now + 45 * 60 * 1000
                    del open_pos[sym]
                    continue

                if not pos["tp1_hit"] and l <= pos["tp1"]:
                    pos["tp1_hit"] = True
                    cm = pos["init_margin"] * tp1_share
                    fee = cm * lev * rt_cost_per_side
                    total_commission += fee
                    pnl = cm * ((entry - pos["tp1"]) / entry) * lev - fee
                    cash += cm + pnl
                    pos["realized"] += pnl
                    pos["margin"] -= cm
                    pos["sl"] = min(pos["sl"], entry * 0.9980)

                if pos["tp1_hit"] and not pos["tp2_hit"] and l <= pos["tp2"]:
                    pos["tp2_hit"] = True
                    cm = pos["margin"] * tp2_rem_share
                    fee = cm * lev * rt_cost_per_side
                    total_commission += fee
                    pnl = cm * ((entry - pos["tp2"]) / entry) * lev - fee
                    cash += cm + pnl
                    pos["realized"] += pnl
                    pos["margin"] -= cm
                    if not legacy_churn_mode:
                        pos["sl"] = min(pos["sl"], entry - 1.2 * pos["risk_dist"])

                pos["lowest"] = min(pos["lowest"], l)
                if legacy_churn_mode and pos["tp1_hit"]:
                    trail_p = pos["lowest"] * (1.0 + 0.007)
                    if trail_p < pos["sl"]:
                        pos["sl"] = trail_p
                elif pos["tp1_hit"] and (pos["tp2_hit"] or pos["lowest"] <= entry - 2.2 * pos["risk_dist"]):
                    trail_p = pos["lowest"] * (1.0 + max(atr_pct * atr_trail_mult, 0.013))
                    if trail_p < pos["sl"]:
                        pos["sl"] = trail_p

                if not legacy_churn_mode and not pos["tp1_hit"] and pos["bars_held"] >= time_stop_bars:
                    if (entry - cl) / pos["risk_dist"] < 0.45:
                        fee = pos["margin"] * lev * rt_cost_per_side
                        total_commission += fee
                        pnl = pos["margin"] * ((entry - cl) / entry) * lev - fee
                        cash += max(pos["margin"] + pnl, 0.0)
                        pos["realized"] += pnl
                        trades.append({"sym": sym, "side": side, "pnl": pos["realized"]})
                        r_mults.append(pos["realized"] / pos["risk_usd"])
                        if pos["realized"] <= -0.15:
                            daily_losses += 1
                        lockouts[sym] = t_now + 20 * 60 * 1000
                        del open_pos[sym]
                        continue

                unreal += pos["margin"] * ((entry - cl) / entry) * lev

        eq = cash + sum(p["margin"] for p in open_pos.values()) + unreal
        peak_eq = max(peak_eq, eq)
        max_dd = max(max_dd, (peak_eq - eq) / peak_eq if peak_eq > 0 else 0.0)

        # 2. ПОИСК СТРУКТУРНЫХ ПРОБОЕВ ПО ЗАКРЫТОЙ СВЕЧЕ [idx - 1]
        max_daily = 999 if legacy_churn_mode else 3
        if len(open_pos) < 2 and daily_losses < max_daily and cash >= 2.0:
            cands = []
            for sym, cdls in all_data.items():
                if sym == "BTCUSDT" or sym in open_pos or t_now < lockouts.get(sym, 0):
                    continue
                idx = ind[sym]["time_idx"].get(t_now)
                if idx is None or idx < max(lookback + 5, 30):
                    continue

                sig = cdls[idx - 1]
                prev = cdls[idx - 2]
                ep = cdls[idx]["open"]
                pct_5m = (sig["close"] - prev["close"]) / prev["close"] * 100.0
                rng = max(sig["high"] - sig["low"], 1e-9)
                uw = (sig["high"] - max(sig["open"], sig["close"])) / rng
                lw = (min(sig["open"], sig["close"]) - sig["low"]) / rng
                atr_pct = ind[sym]["atr"][idx - 1] / sig["close"]
                rsi = ind[sym]["rsi"][idx - 1]

                if legacy_churn_mode:
                    avg_v = sum(x["quote_vol"] for x in cdls[idx - 11: idx - 1]) / 10.0
                    surge = sig["quote_vol"] / avg_v if avg_v > 0 else 1.0
                    sl_l = min(max((ep - min(prev["low"], sig["low"]) * 0.999) / ep, atr_pct, 0.004), 0.012)
                    sl_s = min(max((max(prev["high"], sig["high"]) * 1.001 - ep) / ep, atr_pct, 0.004), 0.012)
                    if surge >= 1.25 and pct_5m >= 0.45 and lw >= 0.12 and uw <= 0.38 and rsi <= 75.0:
                        cands.append((abs(pct_5m) * surge, sym, "LONG", ep, sl_l))
                    elif surge >= 1.25 and pct_5m <= -0.45 and uw >= 0.12 and lw <= 0.38 and rsi >= 25.0:
                        cands.append((abs(pct_5m) * surge, sym, "SHORT", ep, sl_s))
                    continue

                avg_v = sum(x["quote_vol"] for x in cdls[idx - 21: idx - 1]) / 20.0
                surge = sig["quote_vol"] / avg_v if avg_v > 0 else 1.0
                if surge < min_surge:
                    continue

                clv_l = (sig["close"] - sig["low"]) / rng
                clv_s = (sig["high"] - sig["close"]) / rng
                ema9, ema21 = ind[sym]["ema9"][idx - 1], ind[sym]["ema21"][idx - 1]
                if abs(sig["close"] - ema21) / max(ema21, 1e-9) > 0.035:
                    continue

                sh20 = max(x["high"] for x in cdls[idx - 1 - lookback: idx - 1])
                sl20 = min(x["low"] for x in cdls[idx - 1 - lookback: idx - 1])
                sh12 = max(x["high"] for x in cdls[idx - 13: idx - 1])
                sl12 = min(x["low"] for x in cdls[idx - 13: idx - 1])

                brk_l = (sig["close"] > sh20) or (surge >= 2.8 and sig["close"] > sh12 and ema9 >= ema21)
                sl_dist_l = max((ep - min(prev["low"], sig["low"]) * 0.999) / ep, 1.2 * atr_pct, 0.005)
                is_l = (
                    brk_l and pct_5m >= max(min_impulse, atr_pct * 90.0) and
                    clv_l >= min_clv and uw <= max_wick_exh and
                    sig["close"] > ema9 and ema9 >= ema21 * 0.998 and
                    48.0 <= rsi <= 86.0 and 0.005 <= sl_dist_l <= 0.022 and not btc_dump
                )

                brk_s = (sig["close"] < sl20) or (surge >= 2.8 and sig["close"] < sl12 and ema9 <= ema21)
                sl_dist_s = max((max(prev["high"], sig["high"]) * 1.001 - ep) / ep, 1.2 * atr_pct, 0.005)
                is_s = (
                    brk_s and pct_5m <= -max(min_impulse, atr_pct * 90.0) and
                    clv_s >= min_clv and lw <= max_wick_exh and
                    sig["close"] < ema9 and ema9 <= ema21 * 1.002 and
                    14.0 <= rsi <= 52.0 and 0.005 <= sl_dist_s <= 0.022 and not btc_pump
                )

                if is_l:
                    mlp = float(ind[sym]["ml_long"][idx - 1])
                    if mlp >= ml_min_prob:
                        cands.append((abs(pct_5m) * surge * clv_l * (0.5 + mlp), sym, "LONG", ep, sl_dist_l))
                elif is_s:
                    mlp = float(ind[sym]["ml_short"][idx - 1])
                    if mlp >= ml_min_prob:
                        cands.append((abs(pct_5m) * surge * clv_s * (0.5 + mlp), sym, "SHORT", ep, sl_dist_s))

            cands.sort(reverse=True)
            slots = 1 if legacy_churn_mode else (2 - len(open_pos))
            for _, sym, side, ep, sl_dist in cands[:slots]:
                cur_eq = max(15.0, cash + sum(p["margin"] for p in open_pos.values()))
                if legacy_churn_mode:
                    mg = min(4.0, cash * 0.45)
                    risk_usd = mg * leverage * sl_dist
                else:
                    risk_usd = cur_eq * risk_pct
                    mg = min((risk_usd / (sl_dist + 2 * rt_cost_per_side)) / leverage, cash * 0.45)

                if mg < 1.5 or cash < mg + 0.1:
                    continue
                fee_in = mg * leverage * rt_cost_per_side
                total_commission += fee_in
                cash -= (mg + fee_in)
                rd = ep * sl_dist

                if legacy_churn_mode:
                    tp1_p = ep * (1.012 if side == "LONG" else 0.988)
                    tp2_p = ep * (1.024 if side == "LONG" else 0.976)
                else:
                    tp1_p = ep + max(tp1_r * rd, ep * 0.012) if side == "LONG" else ep - max(tp1_r * rd, ep * 0.012)
                    tp2_p = ep + max(tp2_r * rd, ep * 0.024) if side == "LONG" else ep - max(tp2_r * rd, ep * 0.024)

                open_pos[sym] = {
                    "side": side, "entry": ep, "margin": mg, "init_margin": mg, "lev": leverage,
                    "sl": ep - rd if side == "LONG" else ep + rd,
                    "tp1": tp1_p, "tp2": tp2_p,
                    "risk_dist": rd, "risk_usd": max(risk_usd, 0.1),
                    "tp1_hit": False, "tp2_hit": False, "bars_held": 0,
                    "highest": ep, "lowest": ep, "realized": -fee_in
                }

    # Честное закрытие остаточных позиций в конце периода
    for sym, pos in list(open_pos.items()):
        cl = all_data[sym][-1]["close"]
        raw_p = (cl - pos["entry"]) / pos["entry"] if pos["side"] == "LONG" else (pos["entry"] - cl) / pos["entry"]
        fee = pos["margin"] * pos["lev"] * rt_cost_per_side
        total_commission += fee
        pnl = pos["margin"] * raw_p * pos["lev"] - fee
        cash += max(pos["margin"] + pnl, 0.0)
        pos["realized"] += pnl
        trades.append({"sym": sym, "side": pos["side"], "pnl": pos["realized"]})
        r_mults.append(pos["realized"] / pos["risk_usd"])

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0

    return {
        "final_balance": round(cash, 2),
        "net_pnl": round(cash - initial_balance, 2),
        "roi_pct": round((cash - initial_balance) / initial_balance * 100.0, 1),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "max_drawdown_pct": round(max_dd * 100.0, 1),
        "profit_factor": profit_factor,
        "expectancy_r": round(sum(r_mults) / max(1, len(r_mults)), 3),
        "total_commission": round(total_commission, 2)
    }


if __name__ == "__main__":
    cdata = get_7d_data(prefer_extended_universe=True)
    pre = precompute_indicators(cdata)
    n_pairs = len([k for k in cdata if k != "BTCUSDT"])
    n_bars = sum(len(v) for v in cdata.values())
    print(f"\n🔬 ЧЕСТНЫЙ АУДИТ СТРАТЕГИЙ НА {n_pairs} ПАРАХ ({n_bars} 5m свечей, БЕЗ LOOKAHEAD, комиссия+проскальзывание 0.12%):")
    print("=" * 122)
    print(f"{'Конфигурация':<46} | {'Баланс':<8} | {'Чистый PnL':<10} | {'ROI':<8} | {'WR':<6} | {'Сделок':<6} | {'DD':<7} | {'PF':<5} | {'Exp(R)':<7}")
    print("-" * 122)

    configs = [
        ("🚀 Rocket Hunter Standard (12x, Риск 2.5%, ML>=42%)", dict(leverage=12, risk_pct=0.025, ml_min_prob=0.42)),
        ("🔥 Rocket Hunter Compound (15x, Риск 3.2%, ML>=42%)", dict(leverage=15, risk_pct=0.032, ml_min_prob=0.42)),
        ("🛡️ Rocket Hunter Conservative (10x, Риск 2.0%, ML>=48%)", dict(leverage=10, risk_pct=0.020, ml_min_prob=0.48)),
        ("⚡ Rocket Hunter Pure Price-Action (Без ML фильтра)", dict(leverage=12, risk_pct=0.025, ml_min_prob=0.00)),
        ("❌ Старый скальпер (Фитиль>=12%, Трейл 0.7%, Обрез SL)", dict(leverage=10, legacy_churn_mode=True)),
    ]

    for label, kw in configs:
        r = simulate_strategy(cdata, initial_balance=20.0, precomputed=pre, **kw)
        print(
            f"{label:<46} | ${r['final_balance']:<7.2f} | {r['net_pnl']:+8.2f}$  | {r['roi_pct']:+6.1f}% | "
            f"{r['win_rate']:<5.1f}% | {r['total_trades']:<6} | {r['max_drawdown_pct']:<6.1f}% | {r['profit_factor']:<5.2f} | {r['expectancy_r']:+.3f}R"
        )
    print("=" * 122)
