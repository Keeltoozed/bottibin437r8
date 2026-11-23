"""
Бэктест входов/выходов бота на 5m-свечах (candles_cache_7d.json).
Запуск:  python3 backtest_futures.py
Все результаты в R (1R = риск на сделку), уже с комиссиями+проскальзыванием 0.06% на сторону.
Внимание: выборка маленькая (12 монет, 7 дней) — это проверка направления, а не гарантия прибыли.
"""
import json, os, sys, itertools, statistics as st

FEE_RT = 0.0012          # 0.06% вход + 0.06% выход
BASE = dict(
    rvol=1.8, v3=1.15, lookback=20, fast_lb=12, fast_surge=2.8,
    min_clv=0.68, wick_max=0.28, ext_max=0.035, impulse=0.60,
    sl_min=0.005, sl_max=0.022, atr_sl_mult=1.2,
    tp1_r=2.0, tp2_r=3.5, tp1_frac=0.25, tp2_frac=0.25,
    trail_atr=2.5, trail_min=0.015, trail_act_r=2.2, be_buf=0.002,
    time_stop_min=35, time_stop_r=0.45,
    trend_filter=False,      # торговать только по тренду EMA200 (5m) и EMA50
    fail_exit=False,         # выход при возврате цены под уровень пробоя
    max_pos=2, cooldown_min=10, stop_lock_min=90,
    min_avg_qv=0.0,
)

# Настройки, которые теперь стоят в config.py (RVOL>=3, оборот 5m >= $50k, тайм-стоп 60м / <0.3R)
FIXED = dict(BASE, rvol=3.0, min_avg_qv=50000, time_stop_min=60, time_stop_r=0.3)

def ema_series(vals, n):
    k = 2.0 / (n + 1); out = []; e = vals[0]
    for v in vals:
        e = v * k + e * (1 - k); out.append(e)
    return out

def prep(candles):
    c = [x['close'] for x in candles]
    h = [x['high'] for x in candles]; l = [x['low'] for x in candles]
    o = [x['open'] for x in candles]; q = [x['quote_vol'] for x in candles]
    tr = [h[0]-l[0]] + [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(c))]
    return dict(c=c, h=h, l=l, o=o, q=q, tr=tr, t=[x['time'] for x in candles],
                e9=ema_series(c, 9), e21=ema_series(c, 21), e50=ema_series(c, 50), e200=ema_series(c, 200))

def rsi14(c, i):
    g = l = 0.0
    for j in range(i-13, i+1):
        d = c[j]-c[j-1]
        if d >= 0: g += d
        else: l -= d
    if l == 0: return 100.0 if g > 0 else 50.0
    return 100 - 100/(1+(g/14)/(l/14))

def signal(D, i, P):
    """Сигнал по закрытой свече i. Вход — по open свечи i+1. Возвращает (side, sl_pct, atr_pct, level) или None."""
    if i < 210 or i+1 >= len(D['c']): return None
    c, h, l, o, q = D['c'], D['h'], D['l'], D['o'], D['q']
    rng = max(h[i]-l[i], 1e-12)
    avg_q = sum(q[i-20:i]) / 20
    if avg_q <= 0 or avg_q < P['min_avg_qv']: return None
    surge = q[i] / avg_q
    if surge < P['rvol']: return None
    v3 = (sum(q[i-2:i+1]) / 3) / max(avg_q, 1)
    if v3 < P['v3']: return None
    atr = sum(D['tr'][i-13:i+1]) / 14; atr_pct = atr / c[i]
    pct5 = (c[i]-c[i-1]) / c[i-1] * 100
    if abs(pct5) < max(P['impulse'], atr_pct*100*0.9): return None
    entry = o[i+1]
    e9, e21, e50 = D['e9'][i], D['e21'][i], D['e50'][i]
    ext = abs(c[i]-e21)/e21
    if ext > P['ext_max']: return None
    rsi = rsi14(c, i)
    hi20 = max(h[i-P['lookback']:i]); lo20 = min(l[i-P['lookback']:i])
    hi12 = max(h[i-P['fast_lb']:i]); lo12 = min(l[i-P['fast_lb']:i])
    body_top, body_bot = max(o[i], c[i]), min(o[i], c[i])
    uw = (h[i]-body_top)/rng; lw = (body_bot-l[i])/rng
    clv_l = (c[i]-l[i])/rng; clv_s = (h[i]-c[i])/rng
    # 15m тренд
    c15 = [c[j] for j in range(i, i-3*26, -3)][::-1]
    e9_15, e21_15 = ema_series(c15, 9)[-1], ema_series(c15, 21)[-1]
    if c15[-1] >= e21_15*0.998 and e9_15 >= e21_15*0.998: t15 = 'BULL'
    elif c15[-1] <= e21_15*1.002 and e9_15 <= e21_15*1.002: t15 = 'BEAR'
    else: t15 = 'CHOP'
    # LONG
    brk_l = c[i] > hi20 or (surge >= P['fast_surge'] and c[i] > hi12 and e9 >= e21)
    if (brk_l and pct5 > 0 and clv_l >= P['min_clv'] and uw <= P['wick_max'] and c[i] > e9 and e9 >= e21*0.998
            and 48 <= rsi <= 86 and t15 in ('BULL', 'CHOP') and c[i] >= e50*0.995
            and (not P['trend_filter'] or (c[i] > D['e200'][i] and e50 > D['e200'][i]))
            and entry >= c[i]*0.995 and (entry-c[i])/c[i] <= 0.015):
        raw = (entry - min(l[i-1], l[i])*(1-0.001))/entry
        sl = max(raw, P['atr_sl_mult']*atr_pct, P['sl_min'])
        if P['sl_min'] <= sl <= P['sl_max']: return ('LONG', sl, atr_pct, hi20)
    brk_s = c[i] < lo20 or (surge >= P['fast_surge'] and c[i] < lo12 and e9 <= e21)
    if (brk_s and pct5 < 0 and clv_s >= P['min_clv'] and lw <= P['wick_max'] and c[i] < e9 and e9 <= e21*1.002
            and 14 <= rsi <= 52 and t15 in ('BEAR', 'CHOP') and c[i] <= e50*1.005
            and (not P['trend_filter'] or (c[i] < D['e200'][i] and e50 < D['e200'][i]))
            and entry <= c[i]*1.005 and (c[i]-entry)/c[i] <= 0.015):
        raw = (max(h[i-1], h[i])*(1+0.001) - entry)/entry
        sl = max(raw, P['atr_sl_mult']*atr_pct, P['sl_min'])
        if P['sl_min'] <= sl <= P['sl_max']: return ('SHORT', sl, atr_pct, lo20)
    return None

def run_trade(D, i0, side, sl_pct, atr_pct, level, P):
    """i0 — индекс свечи входа. Возвращает (R_net, причина, длительность_баров, индекс_выхода)."""
    h, l, c, o = D['h'], D['l'], D['c'], D['o']
    s = 1 if side == 'LONG' else -1
    entry = o[i0]
    risk = entry*sl_pct
    sl = entry - s*risk
    tp1 = entry + s*max(P['tp1_r']*risk, entry*0.012)
    tp2 = entry + s*max(P['tp2_r']*risk, entry*0.024)
    rem = 1.0; acc = 0.0            # acc — суммарное движение в долях цены * доля позиции
    tp1_hit = tp2_hit = False
    best = entry
    for k in range(i0, len(c)):
        hi, lo = h[k], l[k]
        # 1) стоп (пессимистично — первым)
        hit_stop = (lo <= sl) if s == 1 else (hi >= sl)
        if hit_stop:
            acc += rem * s*(sl-entry)/entry
            why = 'trail' if tp2_hit else ('breakeven' if tp1_hit else 'stop')
            return finish(acc, sl_pct), why, k-i0, k
        # 2) цели
        if not tp1_hit and ((hi >= tp1) if s == 1 else (lo <= tp1)):
            tp1_hit = True; acc += P['tp1_frac']*s*(tp1-entry)/entry; rem -= P['tp1_frac']
            sl = entry*(1+s*P['be_buf'])
        if tp1_hit and not tp2_hit and ((hi >= tp2) if s == 1 else (lo <= tp2)):
            tp2_hit = True; acc += P['tp2_frac']*s*(tp2-entry)/entry; rem -= P['tp2_frac']
            sl = max(sl, entry+1.2*risk) if s == 1 else min(sl, entry-1.2*risk)
        # 3) трейл
        best = max(best, hi) if s == 1 else min(best, lo)
        if tp1_hit and (tp2_hit or abs(best-entry) >= P['trail_act_r']*risk):
            td = max(atr_pct*P['trail_atr'], P['trail_min'])
            ns = best*(1-td) if s == 1 else best*(1+td)
            sl = max(sl, ns) if s == 1 else min(sl, ns)
        # 4) выход при провале пробоя (возврат за уровень пробоя на закрытии)
        if P['fail_exit'] and not tp1_hit and k-i0 <= 6:
            back = (c[k] < level*0.9995) if s == 1 else (c[k] > level*1.0005)
            if back:
                acc += rem*s*(c[k]-entry)/entry
                return finish(acc, sl_pct), 'fail_exit', k-i0, k
        # 5) тайм-стоп
        if not tp1_hit and (k-i0+1)*5 >= P['time_stop_min']:
            cur_r = s*(c[k]-entry)/risk
            if cur_r < P['time_stop_r']:
                acc += rem*s*(c[k]-entry)/entry
                return finish(acc, sl_pct), 'time', k-i0, k
    acc += rem*s*(c[-1]-entry)/entry
    return finish(acc, sl_pct), 'eod', len(c)-i0, len(c)-1

def finish(move, sl_pct):
    return (move - FEE_RT) / (sl_pct + FEE_RT)

def backtest(data, P):
    sigs = []
    for sym, D in data.items():
        for i in range(210, len(D['c'])-1):
            sg = signal(D, i, P)
            if sg: sigs.append((D['t'][i], sym, i, sg))
    sigs.sort()
    trades = []; open_pos = {}; lock = {}
    for t, sym, i, sg in sigs:
        t_entry = data[sym]['t'][i+1]
        for s_, (te, _) in list(open_pos.items()):
            if te <= t_entry: del open_pos[s_]
        if sym in open_pos or len(open_pos) >= P['max_pos']: continue
        if t_entry < lock.get(sym, 0): continue
        side, sl_pct, atr_pct, level = sg
        r, why, bars, k = run_trade(data[sym], i+1, side, sl_pct, atr_pct, level, P)
        t_exit = data[sym]['t'][min(k, len(data[sym]['t'])-1)]
        open_pos[sym] = (t_exit, side)
        lock[sym] = t_exit + (P['stop_lock_min'] if why == 'stop' else P['cooldown_min'])*60000
        trades.append(dict(sym=sym, side=side, r=r, why=why, bars=bars, t=t_entry))
    return trades

def summarize(trades):
    if not trades: return dict(n=0)
    rs = [x['r'] for x in trades]; w = [r for r in rs if r > 0]; lo = [r for r in rs if r <= 0]
    pf = (sum(w)/-sum(lo)) if lo and sum(lo) < 0 else float('inf')
    eq = 0; peak = 0; dd = 0
    for r in rs:
        eq += r; peak = max(peak, eq); dd = max(dd, peak-eq)
    return dict(n=len(rs), win=round(100*len(w)/len(rs)), sumR=round(sum(rs), 1), avgR=round(sum(rs)/len(rs), 3),
                PF=round(pf, 2), maxDD_R=round(dd, 1))

def load(path):
    raw = json.load(open(path))
    return {k: prep(v) for k, v in raw.items()}

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'candles_cache_7d.json')
    data = load(path)
    print('СТАРЫЕ настройки :', summarize(backtest(data, BASE)))
    print('НОВЫЕ настройки  :', summarize(backtest(data, FIXED)))
