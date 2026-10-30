import requests
import time
import math
from typing import List, Dict, Any, Tuple

# ==============================================================================
# ЗАГРУЗКА ИСТОРИЧЕСКИХ ДАННЫХ ЗА 7 ДНЕЙ (BINANCE VISION API)
# ==============================================================================
def fetch_7d_candles(symbol: str) -> List[Dict[str, float]]:
    """Загружает непрерывную историю 5m свечей за последние 7 суток (2016 свечей)."""
    now_ms = int(time.time() * 1000)
    week_ago_ms = now_ms - (7 * 24 * 60 * 60 * 1000)
    
    all_candles = []
    start = week_ago_ms
    
    while start < now_ms:
        url = "https://data-api.binance.vision/api/v3/klines"
        params = {"symbol": symbol, "interval": "5m", "startTime": start, "limit": 1000}
        try:
            r = requests.get(url, params=params, timeout=5)
            if r.status_code != 200:
                break
            chunk = r.json()
            if not chunk or not isinstance(chunk, list):
                break
            for c in chunk:
                all_candles.append({
                    "time": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "quote_vol": float(c[7])
                })
            start = chunk[-1][0] + (5 * 60 * 1000)
            if len(chunk) < 1000:
                break
        except Exception as e:
            print(f"Ошибка загрузки {symbol}: {e}")
            break
            
    return all_candles

# ==============================================================================
# СИМУЛЯЦИЯ СТРАТЕГИИ A: СТАРЫЙ ПОДХОД (ФИКСИРОВАННАЯ МАРЖА $5, 75x БЕЗ R-МЕНЕДЖМЕНТА)
# ==============================================================================
def simulate_old_strategy(candles: List[Dict[str, float]], initial_balance: float = 20.0) -> Dict[str, Any]:
    balance = initial_balance
    peak_balance = balance
    max_drawdown = 0.0
    trades = []
    
    in_pos = False
    entry_p = 0.0
    wick_sl = 0.0
    tp1_p = 0.0
    tp2_p = 0.0
    tp1_hit = False
    pos_margin = 5.0
    lev = 75
    
    for i in range(20, len(candles)):
        c = candles[i]
        prior = candles[i-15:i]
        
        # Обновление просадки
        equity = balance + (pos_margin * ((c['close'] - entry_p) / entry_p) * lev if in_pos else 0.0)
        peak_balance = max(peak_balance, equity)
        dd = (peak_balance - equity) / peak_balance if peak_balance > 0 else 0.0
        max_drawdown = max(max_drawdown, dd)
        
        # 1. Сопровождение открытой позиции
        if in_pos:
            # Стоп-лосс
            if c['low'] <= wick_sl:
                # Фиксация убытка
                loss_pct = (wick_sl - entry_p) / entry_p
                realized_pnl = pos_margin * loss_pct * lev
                balance += (pos_margin + realized_pnl)
                trades.append({
                    "type": "LOSS_SL",
                    "pnl": round(realized_pnl, 2),
                    "exit_price": wick_sl,
                    "reason": "Wick SL Hit"
                })
                in_pos = False
                continue
                
            # TP1 (+2.2%)
            if not tp1_hit and c['high'] >= tp1_p:
                tp1_hit = True
                wick_sl = entry_p * 1.001 # безубыток
                # фиксация 50%
                half_margin = pos_margin * 0.5
                win_pct = (tp1_p - entry_p) / entry_p
                realized_pnl = half_margin * win_pct * lev
                balance += (half_margin + realized_pnl)
                pos_margin -= half_margin
                
            # TP2 (+4.5%)
            if tp1_hit and c['high'] >= tp2_p:
                win_pct = (tp2_p - entry_p) / entry_p
                realized_pnl = pos_margin * win_pct * lev
                balance += (pos_margin + realized_pnl)
                trades.append({
                    "type": "WIN_TP2",
                    "pnl": round(realized_pnl, 2),
                    "exit_price": tp2_p,
                    "reason": "TP2 Hit (+4.5%)"
                })
                in_pos = False
                continue
                
        # 2. Поиск точки входа (старый импульс)
        else:
            if balance < 5.0:
                break # банк слит
                
            avg_vol = sum(x['quote_vol'] for x in prior[-10:]) / 10.0
            surge = c['quote_vol'] / avg_vol if avg_vol > 0 else 1.0
            pct_5m = (c['close'] - candles[i-1]['close']) / candles[i-1]['close'] * 100
            
            # Пробойная свеча
            if surge >= 1.5 and pct_5m >= 0.5:
                entry_p = c['close']
                recent_low = min(x['low'] for x in candles[i-3:i+1])
                wick_sl = recent_low * 0.9985
                sl_dist = (entry_p - wick_sl) / entry_p
                
                # Если стоп в пределах 1.5%
                if 0.003 <= sl_dist <= 0.015:
                    pos_margin = 5.0
                    balance -= pos_margin
                    tp1_p = entry_p * 1.022
                    tp2_p = entry_p * 1.045
                    tp1_hit = False
                    in_pos = True
                    
    # Закрываем остаток если есть
    if in_pos:
        loss_pct = (candles[-1]['close'] - entry_p) / entry_p
        balance += pos_margin + (pos_margin * loss_pct * lev)
        
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    
    return {
        "final_balance": round(balance, 2),
        "net_pnl": round(balance - initial_balance, 2),
        "roi_pct": round((balance - initial_balance) / initial_balance * 100, 1),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "max_drawdown_pct": round(max_drawdown * 100, 1)
    }

# ==============================================================================
# СИМУЛЯЦИЯ СТРАТЕГИИ B: ДИСЦИПЛИНА DAY-TRADER-SKILL (ФИКСИРОВАННЫЙ РИСК 1R, ЦЕЛИ 2R / 3R)
# ==============================================================================
def simulate_daytrader_strategy(candles: List[Dict[str, float]], initial_balance: float = 20.0) -> Dict[str, Any]:
    balance = initial_balance
    peak_balance = balance
    max_drawdown = 0.0
    trades = []
    
    in_pos = False
    entry_p = 0.0
    stop_p = 0.0
    tp1_2r = 0.0
    tp2_3r = 0.0
    tp1_hit = False
    shares_qty = 0.0
    margin_used = 0.0
    risk_r_usd = 0.80 # Фиксированный риск на сделку 80 центов (4% от депозита $20)
    
    # Правило дневного лимита потерь (Circuit Breaker: макс -$2.40 в день)
    daily_loss = 0.0
    current_day = None
    
    for i in range(25, len(candles)):
        c = candles[i]
        bar_day = time.strftime('%Y-%m-%d', time.gmtime(c['time'] / 1000))
        if bar_day != current_day:
            current_day = bar_day
            daily_loss = 0.0 # сброс дневного лимита
            
        prior_20 = candles[i-20:i]
        
        # Обновление просадки
        equity = balance + (shares_qty * (c['close'] - entry_p) if in_pos else 0.0)
        peak_balance = max(peak_balance, equity)
        dd = (peak_balance - equity) / peak_balance if peak_balance > 0 else 0.0
        max_drawdown = max(max_drawdown, dd)
        
        # 1. Сопровождение сделки по правилам day-trader-skill
        if in_pos:
            # Стоп-лосс (жесткий контроль R)
            if c['low'] <= stop_p:
                loss_usd = shares_qty * (stop_p - entry_p)
                balance += (margin_used + loss_usd)
                daily_loss += abs(loss_usd)
                trades.append({
                    "type": "LOSS_1R",
                    "pnl": round(loss_usd, 2),
                    "r_multiple": -1.0,
                    "reason": "1R Stop Hit"
                })
                in_pos = False
                continue
                
            # TP1: Достижение цели 2R (Entry + 2 * Risk)
            if not tp1_hit and c['high'] >= tp1_2r:
                tp1_hit = True
                # Закрываем 50% позиции и фиксируем +1R
                half_shares = shares_qty * 0.5
                win_usd = half_shares * (tp1_2r - entry_p)
                balance += (margin_used * 0.5 + win_usd)
                margin_used *= 0.5
                shares_qty -= half_shares
                # Переносим стоп в безубыток (+0.05% на комиссию)
                stop_p = entry_p * 1.0005
                
            # TP2: Достижение цели 3R (Entry + 3 * Risk)
            if tp1_hit and c['high'] >= tp2_3r:
                win_usd = shares_qty * (tp2_3r - entry_p)
                balance += (margin_used + win_usd)
                trades.append({
                    "type": "WIN_3R",
                    "pnl": round(win_usd + (risk_r_usd * 1.0), 2), # суммарный профит сделки
                    "r_multiple": 2.5,
                    "reason": "3R Runner Target Hit!"
                })
                in_pos = False
                continue
                
        # 2. Поиск входа: подтвержденное закрытие свечи выше уровня (Closed Bar Breakout)
        else:
            if balance < 5.0 or daily_loss >= 2.40:
                continue # защита депозита: дневной лимит сработал
                
            range_high = max(x['high'] for x in prior_20)
            range_low = min(x['low'] for x in prior_20)
            
            # Пробой подтверждается ЗАКРЫТИЕМ свечи выше максимума 20 свечей с объёмом
            prev_c = candles[i-1]
            if c['close'] > range_high and c['quote_vol'] > sum(x['quote_vol'] for x in prior_20[-5:]) / 5.0 * 1.3:
                # Вход на откате или закрытии
                entry_p = c['close']
                # Стоп под фитиль пробойной формации (trader-exit)
                wick_low = min(candles[i-1]['low'], c['low'])
                stop_p = wick_low * 0.999
                
                risk_per_coin = entry_p - stop_p
                risk_pct = risk_per_coin / entry_p
                
                # Фильтр: расстояние до стопа должно быть от 0.4% до 1.0% (идеально для 75x)
                if 0.004 <= risk_pct <= 0.010:
                    # РАСЧЕТ РАЗМЕРА ПОЗИЦИИ ИЗ РАСЧЕТА РИСКА $0.80 (trader-budget)
                    notional_pos = risk_r_usd / risk_pct
                    shares_qty = notional_pos / entry_p
                    margin_used = notional_pos / 75.0 # маржа с 75x плечом
                    
                    if balance >= margin_used:
                        balance -= margin_used
                        # Цели 2R и 3R (trader-exit)
                        tp1_2r = entry_p + (2.0 * risk_per_coin)
                        tp2_3r = entry_p + (3.0 * risk_per_coin)
                        tp1_hit = False
                        in_pos = True
                        
    if in_pos:
        win_usd = shares_qty * (candles[-1]['close'] - entry_p)
        balance += margin_used + win_usd
        
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    
    return {
        "final_balance": round(balance, 2),
        "net_pnl": round(balance - initial_balance, 2),
        "roi_pct": round((balance - initial_balance) / initial_balance * 100, 1),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "max_drawdown_pct": round(max_drawdown * 100, 1)
    }

# ==============================================================================
# ЗАПУСК ТЕСТА НА РЕАЛЬНЫХ ДАННЫХ ЗА 7 ДНЕЙ
# ==============================================================================
if __name__ == "__main__":
    symbols = ["SOLUSDT", "PARTIUSDT", "DOGEUSDT", "SUIUSDT", "PEPEUSDT"]
    
    print("=" * 75)
    print("🔬 БЭКТЕСТ НА РЕАЛЬНЫХ ДАННЫХ BINANCE ЗА ПОСЛЕДНИЕ 7 ДНЕЙ (23-30 ОКТ)")
    print(f"Стартовый депозит: $20.00 | Плечо: 75x | Таймфрейм: 5m")
    print("=" * 75)
    
    all_res_a = []
    all_res_b = []
    
    for s in symbols:
        candles = fetch_7d_candles(s)
        if len(candles) < 1000:
            print(f"⚠️ {s}: недостаточно свечей ({len(candles)})")
            continue
            
        res_a = simulate_old_strategy(candles, 20.0)
        res_b = simulate_daytrader_strategy(candles, 20.0)
        
        all_res_a.append(res_a)
        all_res_b.append(res_b)
        
        print(f"\n📊 Результаты по {s} ({len(candles)} свечей за 7 дней):")
        print(f"   [СТАРЫЙ ПОДХОД]   Баланс: ${res_a['final_balance']:<6} | PnL: {res_a['net_pnl']:+6.2f}$ ({res_a['roi_pct']:+5.1f}%) | Винрейт: {res_a['win_rate']:4.1f}% ({res_a['wins']}/{res_a['total_trades']}) | Просадка: {res_a['max_drawdown_pct']}%")
        print(f"   [DAY-TRADER 2R/3R] Баланс: ${res_b['final_balance']:<6} | PnL: {res_b['net_pnl']:+6.2f}$ ({res_b['roi_pct']:+5.1f}%) | Винрейт: {res_b['win_rate']:4.1f}% ({res_b['wins']}/{res_b['total_trades']}) | Просадка: {res_b['max_drawdown_pct']}%")

    # Общие итоги
    tot_a_pnl = sum(r['net_pnl'] for r in all_res_a)
    tot_b_pnl = sum(r['net_pnl'] for r in all_res_b)
    tot_a_trades = sum(r['total_trades'] for r in all_res_a)
    tot_b_trades = sum(r['total_trades'] for r in all_res_b)
    tot_a_wins = sum(r['wins'] for r in all_res_a)
    tot_b_wins = sum(r['wins'] for r in all_res_b)
    
    print("\n" + "=" * 75)
    print("🏆 ОБЩИЙ ИТОГ СРАВНЕНИЯ ЗА НЕДЕЛЮ ПО ВСЕМ ПАРАМ:")
    print(f"❌ СТАРЫЙ ПОДХОД:     PnL: {tot_a_pnl:+6.2f}$ | Сделок: {tot_a_trades} (Винрейт: {tot_a_wins/tot_a_trades*100:.1f}%)")
    print(f"✅ DAY-TRADER (2R/3R): PnL: {tot_b_pnl:+6.2f}$ | Сделок: {tot_b_trades} (Винрейт: {tot_b_wins/tot_b_trades*100:.1f}%)")
    print("=" * 75)

