import os
import json
import time
import requests
from typing import List, Dict, Any

SYMBOLS = [
    "SUIUSDT", "PEPEUSDT", "DOGEUSDT", "NEARUSDT", "SOLUSDT",
    "ENAUSDT", "JUPUSDT", "RENDERUSDT", "WIFUSDT", "APTUSDT",
    "TIAUSDT", "SEIUSDT"
]
CACHE_FILE = "candles_cache_7d.json"

def get_7d_data() -> Dict[str, List[Dict[str, float]]]:
    if os.path.exists(CACHE_FILE):
        print("⚡ Загрузка свечей из локального кэша...")
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
            
    print("🌐 Загрузка свечей с Binance Vision API...")
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (7 * 24 * 60 * 60 * 1000)
    data = {}
    
    for s in SYMBOLS:
        print(f" -> {s}...", end="", flush=True)
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
            except Exception as e:
                break
        if len(cdls) >= 1500:
            data[s] = cdls
            print(f" {len(cdls)} свечей")
        else:
            print(" пропущено")
            
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)
    print("💾 Кэш свечей сохранен!")
    return data

def simulate_strategy(
    all_data: Dict[str, List[Dict[str, float]]],
    leverage: int,
    margin_mode: str, # "fixed_5", "fixed_6", "compound_25", "compound_35"
    min_surge: float = 1.30,
    min_impulse: float = 0.50,
    min_wick_rej: float = 0.20,
    max_wick_exh: float = 0.35,
    tp1_pct: float = 0.015,
    tp2_pct: float = 0.030,
    initial_balance: float = 20.0
) -> Dict[str, Any]:
    
    all_timestamps = set()
    for s, c_list in all_data.items():
        all_timestamps.update(c["time"] for c in c_list)
    timestamps = sorted(list(all_timestamps))
    
    data_by_time = {s: {c["time"]: c for c in c_list} for s, c_list in all_data.items()}
    
    cash = initial_balance
    peak_equity = initial_balance
    max_drawdown = 0.0
    total_commission = 0.0
    taker_fee_pct = 0.0005
    
    open_positions = {}
    trade_history = []
    
    # Circuit breaker: макс 2 убытка в день
    daily_losses_count = 0
    current_day = None
    
    for t_idx in range(25, len(timestamps)):
        t_now = timestamps[t_idx]
        bar_day = time.strftime('%Y-%m-%d', time.gmtime(t_now / 1000))
        if bar_day != current_day:
            current_day = bar_day
            daily_losses_count = 0
            
        unrealized_sum = 0.0
        
        # 1. ОБРАБОТКА ОТКРЫТЫХ ПОЗИЦИЙ
        for sym in list(open_positions.keys()):
            pos = open_positions[sym]
            c = data_by_time[sym].get(t_now)
            if not c:
                continue
                
            entry = pos["entry_price"]
            lev = pos["leverage"]
            side = pos["side"]
            high_p = c["high"]
            low_p = c["low"]
            cur_p = c["close"]
            
            # LONG
            if side == "LONG":
                # Стоп-лосс
                if low_p <= pos["wick_sl"]:
                    exit_price = pos["wick_sl"]
                    raw_pct = (exit_price - entry) / entry
                    pnl = pos["margin"] * raw_pct * lev
                    fee = (pos["margin"] * lev) * taker_fee_pct
                    pnl -= fee
                    total_commission += fee
                    cash += max(pos["margin"] + pnl, 0.0)
                    if pnl < 0:
                        daily_losses_count += 1
                    trade_history.append({"sym": sym, "side": "LONG", "pnl": round(pnl, 2), "roi": raw_pct * lev * 100})
                    del open_positions[sym]
                    continue
                    
                # TP1 (+1.5%)
                if not pos["tp1_hit"] and high_p >= pos["tp1"]:
                    pos["tp1_hit"] = True
                    closed_m = pos["margin"] * 0.50
                    raw_pct = (pos["tp1"] - entry) / entry
                    pnl = closed_m * raw_pct * lev
                    fee = (closed_m * lev) * taker_fee_pct
                    pnl -= fee
                    total_commission += fee
                    cash += (closed_m + pnl)
                    pos["margin"] -= closed_m
                    pos["wick_sl"] = entry * 1.002 # безубыток + комиссия
                    pos["breakeven_set"] = True
                    trade_history.append({"sym": sym, "side": "LONG", "pnl": round(pnl, 2), "roi": raw_pct * lev * 100})
                    
                # TP2 (+3.0%)
                if pos["tp1_hit"] and not pos["tp2_hit"] and high_p >= pos["tp2"]:
                    pos["tp2_hit"] = True
                    closed_m = pos["margin"] * 0.50
                    raw_pct = (pos["tp2"] - entry) / entry
                    pnl = closed_m * raw_pct * lev
                    fee = (closed_m * lev) * taker_fee_pct
                    pnl -= fee
                    total_commission += fee
                    cash += (closed_m + pnl)
                    pos["margin"] -= closed_m
                    trade_history.append({"sym": sym, "side": "LONG", "pnl": round(pnl, 2), "roi": raw_pct * lev * 100})
                    
                # Трейлинг на остаток
                if pos["tp1_hit"]:
                    pos["highest"] = max(pos.get("highest", entry), high_p)
                    trail = pos["highest"] * 0.993
                    if trail > pos["wick_sl"]:
                        pos["wick_sl"] = trail
                    if low_p <= trail:
                        raw_pct = (trail - entry) / entry
                        pnl = pos["margin"] * raw_pct * lev
                        fee = (pos["margin"] * lev) * taker_fee_pct
                        pnl -= fee
                        total_commission += fee
                        cash += max(pos["margin"] + pnl, 0.0)
                        trade_history.append({"sym": sym, "side": "LONG", "pnl": round(pnl, 2), "roi": raw_pct * lev * 100})
                        del open_positions[sym]
                        continue
                        
                unrealized_sum += pos["margin"] * ((cur_p - entry) / entry) * lev

            # SHORT
            else:
                # Стоп-лосс
                if high_p >= pos["wick_sl"]:
                    exit_price = pos["wick_sl"]
                    raw_pct = (entry - exit_price) / entry
                    pnl = pos["margin"] * raw_pct * lev
                    fee = (pos["margin"] * lev) * taker_fee_pct
                    pnl -= fee
                    total_commission += fee
                    cash += max(pos["margin"] + pnl, 0.0)
                    if pnl < 0:
                        daily_losses_count += 1
                    trade_history.append({"sym": sym, "side": "SHORT", "pnl": round(pnl, 2), "roi": raw_pct * lev * 100})
                    del open_positions[sym]
                    continue
                    
                # TP1 (-1.5%)
                if not pos["tp1_hit"] and low_p <= pos["tp1"]:
                    pos["tp1_hit"] = True
                    closed_m = pos["margin"] * 0.50
                    raw_pct = (entry - pos["tp1"]) / entry
                    pnl = closed_m * raw_pct * lev
                    fee = (closed_m * lev) * taker_fee_pct
                    pnl -= fee
                    total_commission += fee
                    cash += (closed_m + pnl)
                    pos["margin"] -= closed_m
                    pos["wick_sl"] = entry * 0.998 # безубыток + комиссия
                    pos["breakeven_set"] = True
                    trade_history.append({"sym": sym, "side": "SHORT", "pnl": round(pnl, 2), "roi": raw_pct * lev * 100})
                    
                # TP2 (-3.0%)
                if pos["tp1_hit"] and not pos["tp2_hit"] and low_p <= pos["tp2"]:
                    pos["tp2_hit"] = True
                    closed_m = pos["margin"] * 0.50
                    raw_pct = (entry - pos["tp2"]) / entry
                    pnl = closed_m * raw_pct * lev
                    fee = (closed_m * lev) * taker_fee_pct
                    pnl -= fee
                    total_commission += fee
                    cash += (closed_m + pnl)
                    pos["margin"] -= closed_m
                    trade_history.append({"sym": sym, "side": "SHORT", "pnl": round(pnl, 2), "roi": raw_pct * lev * 100})
                    
                # Трейлинг на остаток
                if pos["tp1_hit"]:
                    pos["lowest"] = min(pos.get("lowest", entry), low_p)
                    trail = pos["lowest"] * 1.007
                    if trail < pos["wick_sl"]:
                        pos["wick_sl"] = trail
                    if high_p >= trail:
                        raw_pct = (entry - trail) / entry
                        pnl = pos["margin"] * raw_pct * lev
                        fee = (pos["margin"] * lev) * taker_fee_pct
                        pnl -= fee
                        total_commission += fee
                        cash += max(pos["margin"] + pnl, 0.0)
                        trade_history.append({"sym": sym, "side": "SHORT", "pnl": round(pnl, 2), "roi": raw_pct * lev * 100})
                        del open_positions[sym]
                        continue
                        
                unrealized_sum += pos["margin"] * ((entry - cur_p) / entry) * lev

        # Эквити и просадка
        equity = cash + sum(p["margin"] for p in open_positions.values()) + unrealized_sum
        peak_equity = max(peak_equity, equity)
        dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        max_drawdown = max(max_drawdown, dd)
        
        # 2. ПОИСК ВХОДОВ С АВТОРСКИМИ ПРАВИЛАМИ ИИ JEV
        # Защита: максимум 2 позиции одновременно, и не более 2 убытков в день
        if len(open_positions) < 2 and daily_losses_count < 2 and cash >= 3.0:
            candidates = []
            
            for sym, c_list in all_data.items():
                if sym in open_positions:
                    continue
                c_now = data_by_time[sym].get(t_now)
                if not c_now:
                    continue
                    
                c_idx = next((i for i, x in enumerate(c_list) if x["time"] == t_now), None)
                if c_idx is None or c_idx < 15:
                    continue
                    
                c_prev = c_list[c_idx - 1]
                prior_vols = [x["quote_vol"] for x in c_list[c_idx - 11 : c_idx - 1]]
                avg_vol = sum(prior_vols) / len(prior_vols) if prior_vols else 1.0
                
                surge = max(c_prev["quote_vol"], c_now["quote_vol"]) / avg_vol if avg_vol > 0 else 1.0
                pct_5m = (c_now["close"] - c_prev["close"]) / c_prev["close"] * 100
                
                c_range = max(c_now["high"] - c_now["low"], 1e-9)
                body_top = max(c_now["open"], c_now["close"])
                body_bottom = min(c_now["open"], c_now["close"])
                upper_wick = (c_now["high"] - body_top) / c_range
                lower_wick = (body_bottom - c_now["low"]) / c_range
                
                wick_low = min(c_prev["low"], c_now["low"]) * 0.999
                sl_long_dist = (c_now["close"] - wick_low) / c_now["close"]
                
                wick_high = max(c_prev["high"], c_now["high"]) * 1.001
                sl_short_dist = (wick_high - c_now["close"]) / c_now["close"]
                
                # ИИ-фильтр качества входа (Day-Trader JEV rules):
                # 1. Четкий взрыв объема
                # 2. Амплитуда свечи
                # 3. Фитиль защиты уровня >= min_wick_rej
                # 4. Нет истощения (противоположный фитиль <= max_wick_exh)
                # 5. Стоп в пределах скальперского допуска (0.3% - 1.2%)
                is_long = (
                    surge >= min_surge and
                    pct_5m >= min_impulse and
                    lower_wick >= min_wick_rej and
                    upper_wick <= max_wick_exh and
                    0.003 <= sl_long_dist <= 0.012
                )
                
                is_short = (
                    surge >= min_surge and
                    pct_5m <= -min_impulse and
                    upper_wick >= min_wick_rej and
                    lower_wick <= max_wick_exh and
                    0.003 <= sl_short_dist <= 0.012
                )
                
                if is_long:
                    candidates.append({"sym": sym, "side": "LONG", "p": c_now["close"], "sl": wick_low, "score": abs(pct_5m)*surge})
                elif is_short:
                    candidates.append({"sym": sym, "side": "SHORT", "p": c_now["close"], "sl": wick_high, "score": abs(pct_5m)*surge})
                    
            candidates.sort(key=lambda x: x["score"], reverse=True)
            
            for cand in candidates[:1]: # берем самый лучший 1 сетап
                if len(open_positions) >= 2:
                    break
                sym = cand["sym"]
                
                if margin_mode == "fixed_5":
                    act_margin = min(5.0, cash * 0.45)
                elif margin_mode == "fixed_6":
                    act_margin = min(6.0, cash * 0.45)
                elif margin_mode == "compound_25":
                    act_margin = round(min(max(5.0, cash * 0.25), cash * 0.45), 2)
                elif margin_mode == "compound_35":
                    act_margin = round(min(max(6.0, cash * 0.35), cash * 0.45), 2)
                else:
                    act_margin = 5.0
                    
                if cash < act_margin:
                    continue
                    
                entry_p = cand["p"]
                wick_sl = cand["sl"]
                side = cand["side"]
                
                # Комиссия входа
                fee_in = (act_margin * leverage) * taker_fee_pct
                cash -= (act_margin + fee_in)
                total_commission += fee_in
                
                if side == "LONG":
                    risk_d = entry_p - wick_sl
                    tp1 = max(entry_p + 2.0 * risk_d, entry_p * (1.0 + tp1_pct))
                    tp2 = max(entry_p + 3.5 * risk_d, entry_p * (1.0 + tp2_pct))
                else:
                    risk_d = wick_sl - entry_p
                    tp1 = min(entry_p - 2.0 * risk_d, entry_p * (1.0 - tp1_pct))
                    tp2 = min(entry_p - 3.5 * risk_d, entry_p * (1.0 - tp2_pct))
                    
                open_positions[sym] = {
                    "sym": sym, "side": side, "entry_price": entry_p,
                    "margin": act_margin, "leverage": leverage,
                    "wick_sl": wick_sl, "tp1": tp1, "tp2": tp2,
                    "tp1_hit": False, "tp2_hit": False, "breakeven_set": False
                }
                
    # Закрытие остатка
    for sym, pos in list(open_positions.items()):
        c_last = all_data[sym][-1]
        cur_p = c_last["close"]
        raw_pct = (cur_p - pos["entry_price"]) / pos["entry_price"] if pos["side"] == "LONG" else (pos["entry_price"] - cur_p) / pos["entry_price"]
        pnl = pos["margin"] * raw_pct * pos["leverage"]
        fee = (pos["margin"] * pos["leverage"]) * taker_fee_pct
        pnl -= fee
        total_commission += fee
        cash += max(pos["margin"] + pnl, 0.0)
        trade_history.append({"sym": sym, "side": pos["side"], "pnl": round(pnl, 2), "roi": raw_pct * pos["leverage"] * 100})
        
    wins = [t for t in trade_history if t["pnl"] > 0]
    losses = [t for t in trade_history if t["pnl"] < 0]
    win_rate = (len(wins) / len(trade_history) * 100) if trade_history else 0.0
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0
    
    return {
        "final_balance": round(cash, 2),
        "net_pnl": round(cash - initial_balance, 2),
        "roi_pct": round((cash - initial_balance) / initial_balance * 100, 1),
        "total_trades": len(trade_history),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "max_drawdown_pct": round(max_drawdown * 100, 1),
        "profit_factor": profit_factor,
        "total_commission": round(total_commission, 2)
    }

if __name__ == "__main__":
    data = get_7d_data()
    
    print("\n🔍 ТЕСТИРОВАНИЕ РАЗЛИЧНЫХ КОНФИГУРАЦИЙ ДЛЯ НАХОЖДЕНИЯ СВЕРХПРИБЫЛЬНОЙ ВАРИАЦИИ:")
    print("==========================================================================================================================")
    print(f"{'Конфигурация':<42} | {'Баланс':<9} | {'Прибыль':<11} | {'ROI':<8} | {'Винрейт':<8} | {'Сделок':<7} | {'Просадка':<9} | {'PF':<5} | {'Комиссия':<8}")
    print("--------------------------------------------------------------------------------------------------------------------------")
    
    test_configs = [
        # Плечо 75x
        {"label": "1. 75x Turbo (Качественный ИИ фильтр)", "lev": 75, "m_mode": "compound_35", "surge": 1.35, "imp": 0.55, "w_rej": 0.20, "w_exh": 0.35},
        {"label": "2. 75x Selective A+ (Всплеск 1.5x, 0.65% ход)", "lev": 75, "m_mode": "fixed_5", "surge": 1.50, "imp": 0.65, "w_rej": 0.25, "w_exh": 0.30},
        
        # Плечо 35x
        {"label": "3. 35x Optimal (Сложный процент 35%)", "lev": 35, "m_mode": "compound_35", "surge": 1.35, "imp": 0.50, "w_rej": 0.20, "w_exh": 0.35},
        {"label": "4. 35x Sniper (Всплеск 1.45x, импульс 0.6%)", "lev": 35, "m_mode": "compound_25", "surge": 1.45, "imp": 0.60, "w_rej": 0.25, "w_exh": 0.30},
        
        # Плечо 25x
        {"label": "5. 25x Smart Growth (Сложный процент 35%)", "lev": 25, "m_mode": "compound_35", "surge": 1.35, "imp": 0.50, "w_rej": 0.20, "w_exh": 0.35},
        {"label": "6. 25x Disciplined Sniper (1.45x, 0.60%)", "lev": 25, "m_mode": "compound_25", "surge": 1.45, "imp": 0.60, "w_rej": 0.25, "w_exh": 0.30},
        
        # Плечо 20x
        {"label": "7. 20x Safe Compounding (Сложный процент)", "lev": 20, "m_mode": "compound_35", "surge": 1.35, "imp": 0.50, "w_rej": 0.20, "w_exh": 0.35},
        {"label": "8. 20x High-Conviction (1.5x всплеск)", "lev": 20, "m_mode": "fixed_6", "surge": 1.50, "imp": 0.60, "w_rej": 0.25, "w_exh": 0.30},
    ]
    
    best_roi = -999
    best_cfg = None
    
    for cfg in test_configs:
        res = simulate_strategy(
            all_data=data,
            leverage=cfg["lev"],
            margin_mode=cfg["m_mode"],
            min_surge=cfg["surge"],
            min_impulse=cfg["imp"],
            min_wick_rej=cfg["w_rej"],
            max_wick_exh=cfg["w_exh"],
            initial_balance=20.0
        )
        print(f"{cfg['label']:<42} | ${res['final_balance']:<8.2f} | {res['net_pnl']:+9.2f}$ | {res['roi_pct']:+7.1f}% | {res['win_rate']:<7.1f}% | {res['total_trades']:<7} | {res['max_drawdown_pct']:<8.1f}% | {res['profit_factor']:<5.2f} | ${res['total_commission']:<7.2f}")
        if res["roi_pct"] > best_roi:
            best_roi = res["roi_pct"]
            best_cfg = {**cfg, **res}
            
    print("==========================================================================================================================")
