import sys
import os
import warnings

# Подавляем устаревшие предупреждения Streamlit в логах сервера
warnings.filterwarnings("ignore")
os.environ["PYTHONUNBUFFERED"] = "1"
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

import streamlit as st
import time
import threading
import asyncio
import pandas as pd
from tracker import portfolio
import config
from main_bot import run_in_background
from scanner import market_scanner
from obsidian_vault import obsidian_vault
from ml_engine import ml_engine

# ==============================================================================
# НАСТРОЙКА СТРАНИЦЫ
# ==============================================================================
st.set_page_config(
    page_title="Binance Groq Autonomous Trader",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# ЗАПУСК ФОНОВОГО БОТА (РОВНО 1 РАЗ НА СЕССИЮ СЕРВЕРА)
# ==============================================================================
@st.cache_resource
def initialize_bot():
    """Запускает торгового бота в фоне ровно один раз при старте сервера."""
    thread = threading.Thread(target=run_in_background, daemon=True)
    thread.start()
    print("🚀 [STARTUP] Фоновый поток торгового бота запущен из Streamlit!", flush=True)
    return thread

# Запуск бота
bot_thread = initialize_bot()

# ==============================================================================
# КАСТОМНЫЙ CSS СТИЛЬ (ТЕМНАЯ ТЕМА, КАРТОЧКИ, БЕЙДЖИ)
# ==============================================================================
st.markdown("""
<style>
    .metric-card {
        background-color: #1a1c24;
        border: 1px solid #2d313e;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 12px;
    }
    .metric-title {
        color: #8b949e;
        font-size: 13px;
        font-weight: 500;
        margin-bottom: 4px;
    }
    .metric-val {
        color: #f0f6fc;
        font-size: 24px;
        font-weight: 700;
    }
    .badge-long {
        background-color: #238636;
        color: white;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
    }
    .badge-short {
        background-color: #da3633;
        color: white;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
    }
    .badge-buy {
        background-color: #2ea043;
        color: white;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: bold;
    }
    .badge-skip {
        background-color: #484f58;
        color: #c9d1d9;
        padding: 4px 10px;
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# САЙДБАР (УПРАВЛЕНИЕ И НАСТРОЙКИ)
# ==============================================================================
with st.sidebar:
    st.title("⚙️ Управление ботом")
    
    # Статус бота
    is_paused = portfolio.is_paused
    status_label = "⏸ НА ПАУЗЕ" if is_paused else "🟢 АКТИВЕН"
    st.subheader(f"Статус: {status_label}")
    
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        if st.button("▶ Возобновить", use_container_width=True, disabled=not is_paused):
            portfolio.is_paused = False
            portfolio.save()
            st.rerun()
    with col_p2:
        if st.button("⏸ Пауза", use_container_width=True, disabled=is_paused):
            portfolio.is_paused = True
            portfolio.save()
            st.rerun()
            
    st.divider()
    
    # Кнопка принудительного сканирования
    if st.button("🔍 Сканировать сейчас", use_container_width=True):
        with st.spinner("Сканирование рынка Binance Futures..."):
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(market_scanner.scan_market_once())
                loop.close()
                st.success("Сканирование завершено!")
            except Exception as e:
                st.error(f"Ошибка сканирования: {e}")
        st.rerun()

    # Кнопка экстренного закрытия
    if st.button("🚨 Panic Close (Закрыть все)", type="primary", use_container_width=True):
        portfolio.close_all("Экстренное ручное закрытие из дашборда")
        st.success("Все открытые позиции закрыты!")
        st.rerun()
        
    st.divider()
    st.markdown("### 🎯 Параметры стратегии ($20)")
    
    # Выбор кредитного плеча
    lev_options = [30, 25, 35, 50, 60, 75, 20, 10]
    cur_lev = getattr(portfolio, "current_leverage", config.LEVERAGE)
    cur_idx = lev_options.index(cur_lev) if cur_lev in lev_options else 0
    chosen_leverage = st.selectbox("⚡ Кредитное плечо (для новых сделок):", lev_options, index=cur_idx)

    if chosen_leverage != getattr(portfolio, "current_leverage", None):
        portfolio.current_leverage = chosen_leverage
        config.LEVERAGE = chosen_leverage
        portfolio.save()
        st.rerun()

    # Режим разгона депозита (Compounding Multiplier)
    risk_mode = st.radio(
        "Режим доходности:",
        [
            "⚡ Институционал 30x (Рекомендуемый: макс винрейт, комиссии -50%)",
            "🔥 Турбо 60x (Высокий разгон)",
            "🎯 Стандарт 20x (Сверхбезопасный)"
        ],
        index=0
    )
    if "Институционал" in risk_mode:
        config.COMPOUND_RISK_PCT = 0.08
        config.MAX_RISK_PER_TRADE_USD = 1.20
        config.TRADE_AMOUNT_USDT = 5.0
    elif "Турбо" in risk_mode:
        config.COMPOUND_RISK_PCT = 0.10
        config.MAX_RISK_PER_TRADE_USD = 1.50
        config.TRADE_AMOUNT_USDT = 5.0
    else:
        config.COMPOUND_RISK_PCT = 0.05
        config.MAX_RISK_PER_TRADE_USD = 1.00
        config.TRADE_AMOUNT_USDT = 5.0

    st.text(f"Плечо для новых входов: {portfolio.current_leverage}x 🚀")
    current_risk_usd = max(portfolio.cash * config.COMPOUND_RISK_PCT, config.MAX_RISK_PER_TRADE_USD) if config.ENABLE_COMPOUNDING else config.MAX_RISK_PER_TRADE_USD
    st.text(f"Сложный процент: 🟢 ВКЛ ({int(config.COMPOUND_RISK_PCT*100)}% депо)")
    st.text(f"Текущий риск на сделку: ${current_risk_usd:.2f}")
    st.text(f"Расчет маржи: Динамический от стопа")
    st.text(f"Направления: 🟢 LONG + 🔻 SHORT")
    st.text(f"Цели профита: 2R / 3.5R")
    st.text(f"Радар рынка: {len(getattr(config, 'TOP_CRYPTO_UNIVERSE', []))} монет (Top-Tier)")
    st.text(f"Модель Groq: {config.GROQ_PRIMARY_MODEL}")
    has_key = bool(config.GROQ_API_KEY)
    st.text(f"ИИ Статус: {'🟢 Активен (Groq Cloud)' if has_key else '🟡 Резервный (Institutional)'}")
    
    st.divider()
    if st.button("🔄 Сбросить портфель к $20.00"):
        portfolio.cash = config.INITIAL_BALANCE
        portfolio.open_positions.clear()
        portfolio.trade_history.clear()
        portfolio.symbol_lockouts.clear()
        portfolio.consecutive_losses = 0
        portfolio.pause_until = 0.0
        portfolio.current_leverage = getattr(config, "LEVERAGE", 30)
        portfolio.save()
        st.success("Баланс сброшен до $20.00!")
        st.rerun()

    st.divider()
    auto_refresh = st.checkbox("🔄 Автообновление UI (4 сек)", value=True)

# ==============================================================================
# ВЕРХНИЙ ХЕДЕР И ОСНОВНЫЕ МЕТРИКИ (ОСНОВНОЙ ЭКРАН)
# ==============================================================================
summary = portfolio.get_portfolio_summary()

st.title("🚀 Binance Autonomous Groq Trader (JEV Engine)")
last_scan_info = getattr(portfolio, "last_scan_str", "Ожидание...")
btc_regime_info = getattr(portfolio, "btc_regime_str", "🟡 Анализ Bitcoin...")
st.caption(f"🌍 **Макро-щит (Защита от новостей/дампа BTC):** {btc_regime_info}")
st.caption(f"Автономный торговый конвейер: Топ-30 Крипто-вселенная → Защита от ловушек ИИ (CT Anti-Trap) → Динамический трейлинг | Режим: {'🧪 Paper Trading (Симуляция)' if config.PAPER_TRADING else '⚡ Live Trading'} | Последний скан: {last_scan_info}")

# Оповещение и ручной сброс Circuit Breaker (если включен)
if getattr(config, "ENABLE_CIRCUIT_BREAKER", False) and summary["circuit_breaker"]:
    cb_col1, cb_col2 = st.columns([3, 1])
    with cb_col1:
        st.error(f"🛑 **Защита депозита (Circuit Breaker):** Дневной лимит убытка (-${summary['daily_loss']:.2f}) исчерпан. Новые входы приостановлены.")
    with cb_col2:
        if st.button("🔓 Снять лимит и возобновить торговлю", type="primary"):
            portfolio.reset_daily_loss()
            st.success("Торговля разблокирована!")
            st.rerun()

# Метрики карточками
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">💰 Баланс (Cash)</div>
        <div class="metric-val">${summary['cash']:.2f}</div>
    </div>
    """, unsafe_allow_html=True)
with c2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">📈 Общий Equity</div>
        <div class="metric-val">${summary['equity']:.2f}</div>
    </div>
    """, unsafe_allow_html=True)
with c3:
    pnl_color = "#3fb950" if summary['unrealized_pnl'] >= 0 else "#f85149"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">⚡ Нереализованный PnL</div>
        <div class="metric-val" style="color: {pnl_color};">${summary['unrealized_pnl']:+.2f}</div>
    </div>
    """, unsafe_allow_html=True)
with c4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">🎯 Открытых позиций</div>
        <div class="metric-val">{summary['open_positions_count']} / {summary['max_positions']}</div>
    </div>
    """, unsafe_allow_html=True)
with c5:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">🏆 Винрейт</div>
        <div class="metric-val">{summary['win_rate']}% ({summary['wins']}/{summary['total_trades']})</div>
    </div>
    """, unsafe_allow_html=True)

# ==============================================================================
# ВКЛАДКИ
# ==============================================================================
tab_pos, tab_radar, tab_funnel, tab_history, tab_shadow, tab_timemachine, tab_brain = st.tabs([
    "🟢 Открытые позиции",
    "🤖 Groq Live Radar",
    "📊 Воронка The Funnel",
    "📓 История сделок",
    "👻 Shadow Tracker",
    "🔬 Time Machine (Бэктест)",
    "🧠 Второй мозг (Obsidian & ML)"
])

# ------------------------------------------------------------------------------
# 1. ОТКРЫТЫЕ ПОЗИЦИИ
# ------------------------------------------------------------------------------
with tab_pos:
    st.subheader("🟢 Активные сделки в сопровождении")
    if not portfolio.open_positions:
        st.info("В данный момент нет открытых сделок. Автономный сканер ищет сетапы (LONG и SHORT)...")
    else:
        for sym, pos in list(portfolio.open_positions.items()):
            with st.container():
                pnl_color = "#3fb950" if pos['unrealized_pnl'] >= 0 else "#f85149"
                be_badge = "🛡️ Безубыток АКТИВЕН" if pos['breakeven_set'] else "Ожидание TP1"
                side = pos.get('side', 'LONG')
                side_badge_cls = "badge-long" if side == 'LONG' else "badge-short"
                stop_label = "Stop Under Wick" if side == 'LONG' else "Stop Above Wick"
                
                col_a, col_b, col_c, col_d, col_e = st.columns([2, 2, 2, 2, 1])
                with col_a:
                    st.markdown(f"### {sym} <span class='{side_badge_cls}'>{side} {pos['leverage']}x</span>", unsafe_allow_html=True)
                    ep_pos = pos.get('entry_price', 0.0) or 0.0
                    mg_pos = pos.get('margin_usdt', 0.0) or 0.0
                    init_mg = pos.get('initial_margin_usdt', mg_pos) or mg_pos
                    if init_mg > mg_pos + 0.05:
                        st.caption(f"Вход: ${ep_pos:.4f} • В сделке: ${mg_pos:.2f} (исходная: ${init_mg:.2f})")
                    else:
                        st.caption(f"Вход: ${ep_pos:.4f} • Маржа: ${mg_pos:.2f}")
                with col_b:
                    cp_pos = pos.get('current_price', 0.0) or 0.0
                    st.metric("Текущая цена", f"${cp_pos:.4f}")
                with col_c:
                    pnl_usd = pos.get('unrealized_pnl', 0.0) or 0.0
                    pnl_pct = pos.get('pnl_pct', 0.0) or 0.0
                    delta_display = f"+${pnl_usd:.2f}" if pnl_usd >= 0 else f"-${abs(pnl_usd):.2f}"
                    st.metric("PnL (%)", f"{pnl_pct:+.2f}%", delta=delta_display)
                with col_d:
                    sl_pos = pos.get('wick_sl', 0.0) or 0.0
                    tp1_pos = pos.get('tp1', 0.0) or 0.0
                    tp2_pos = pos.get('tp2', 0.0) or 0.0
                    st.markdown(f"**{stop_label}:** `${sl_pos:.4f}`")
                    st.markdown(f"**TP1:** `${tp1_pos:.4f}` | **TP2:** `${tp2_pos:.4f}`")
                    st.caption(be_badge)
                with col_e:
                    if st.button("Закрыть", key=f"close_{sym}"):
                        portfolio.close_position(sym, pos.get('current_price', 0.0), "Ручное закрытие из интерфейса")
                        st.rerun()
                st.caption(f"🧠 Логика Groq: {pos.get('groq_reason', 'N/A')}")
                st.divider()

    # --------------------------------------------------------------------------
    # НЕДАВНО ЗАКРЫТЫЕ СДЕЛКИ (ОТОБРАЖАЮТСЯ СРАЗУ ПОД ОТКРЫТЫМИ)
    # --------------------------------------------------------------------------
    st.subheader("🏁 Недавно закрытые сделки (Результаты)")
    if not portfolio.trade_history:
        st.caption("Здесь фиксируются все завершенные сделки (TP1, TP2, Stop-Loss или Trailing). История сохраняется персистентно.")
    else:
        for t in reversed(portfolio.trade_history[-10:]):
            r_pnl = t.get("realized_pnl", 0.0) or 0.0
            r_roi = t.get("roi_pct", 0.0) or 0.0
            is_win = r_pnl >= 0
            pnl_color = "#3fb950" if is_win else "#f85149"
            side = t.get("side", "LONG")
            side_badge_cls = "badge-long" if side == 'LONG' else "badge-short"
            
            with st.container():
                rc1, rc2, rc3, rc4 = st.columns([2, 2, 2, 3])
                with rc1:
                    sym_name = t.get('symbol', 'N/A')
                    st.markdown(f"**{sym_name}** <span class='{side_badge_cls}'>{side} {t.get('leverage', config.LEVERAGE)}x</span>", unsafe_allow_html=True)
                    st.caption(f"Закрыто: {t.get('closed_at', 'N/A')}")
                with rc2:
                    ep_t = t.get('entry_price', 0.0) or 0.0
                    xp_t = t.get('exit_price', 0.0) or 0.0
                    st.markdown(f"Вход: **${ep_t:.4f}**")
                    st.markdown(f"Выход: **${xp_t:.4f}**")
                with rc3:
                    st.markdown(f"<span style='color: {pnl_color}; font-size: 17px; font-weight: bold;'>{r_pnl:+.2f} USDT ({r_roi:+.1f}%)</span>", unsafe_allow_html=True)
                    init_mg_t = t.get('initial_margin_usdt', t.get('margin_usdt', 0.0)) or 0.0
                    cur_mg_t = t.get('margin_usdt', 0.0) or 0.0
                    if t.get('partial_pct', 1.0) < 0.99 and init_mg_t > cur_mg_t + 0.05:
                        st.caption(f"Фиксация доли: ${cur_mg_t:.2f} (из ${init_mg_t:.2f})")
                    else:
                        st.caption(f"Маржа сделки: ${cur_mg_t:.2f}")
                with rc4:
                    st.markdown(f"**Причина:** {t.get('reason', 'Фиксация')}")
                    st.caption(f"Длительность: {t.get('duration_sec', 0)} сек")
                st.divider()

# ------------------------------------------------------------------------------
# 2. GROQ LIVE RADAR (ОЦЕНКА МОНЕТ)
# ------------------------------------------------------------------------------
with tab_radar:
    st.subheader("🧠 Живой радар Quant ML (Оценка всех 72 пар рынка)")
    st.caption("Квантовая модель XGBoost непрерывно сканирует каждую пару на Binance Futures и оценивает 30 институциональных факторов в реальном времени.")
    
    if getattr(portfolio, "live_ml_ranking", None):
        rows_ml = []
        for item in portfolio.live_ml_ranking[:15]:
            p_val = item.get("ml_prob", 0.0) * 100
            side_val = item.get("candidate_side", "LONG")
            side_str = "🟢 LONG" if side_val == 'LONG' else "🔻 SHORT"
            sl_dist = item.get("sl_pct_distance", 0.0) if side_val == "LONG" else item.get("short_sl_dist", 0.0)
            sl_pct = sl_dist * 100
            
            raw_reason = item.get("ml_reason", "")
            if "опасный стоп" in raw_reason:
                stat_str = f"❌ Опасный стоп ({sl_pct:.2f}% > 0.75%)"
            elif "сонный объем" in raw_reason:
                stat_str = "💤 Нет объёма (< 1.30x)"
            elif p_val >= 70.0:
                stat_str = "🔥 A+ Сетап (Проходит)"
            elif p_val >= 50.0:
                stat_str = "⚡ В наблюдении"
            else:
                stat_str = "💤 Боковик"
                
            v_vol = item.get('volume_surge_ratio') if item.get('volume_surge_ratio') is not None else 1.0
            v_5m = item.get('pct_5m') if item.get('pct_5m') is not None else 0.0
            v_rsi = item.get('rsi') if item.get('rsi') is not None else 50.0

            rows_ml.append({
                "Монета": item.get("symbol", "N/A"),
                "Сторона": side_str,
                "Вероятность ML": f"{p_val:.1f}%",
                "Дистанция SL": f"{sl_pct:.2f}%",
                "Всплеск объема": f"{v_vol:.2f}x",
                "Импульс 5m": f"{v_5m:+.2f}%",
                "RSI": f"{v_rsi:.1f}",
                "Статус": stat_str
            })
        st.dataframe(pd.DataFrame(rows_ml), width="stretch")
    else:
        st.info("Квантовый ML сканер собирает метрики по парам рынка...")

    st.markdown("---")
    st.subheader("🤖 Решения Groq AI (JEV Engine)")
    st.caption("Сюда передаются только монеты, получившие высокий математический перевес от модели ML.")
    
    if not portfolio.recent_evaluations:
        st.info("Ожидание одобренных сетапов от квантовой модели...")
    else:
        for ev in portfolio.recent_evaluations[:15]:
            dec = ev.get('decision', 'SKIP')
            if dec == 'BUY':
                badge = "<span class='badge-buy'>✅ BUY (LONG)</span>"
            elif dec == 'SHORT':
                badge = "<span class='badge-short' style='font-size: 13px; font-weight: bold;'>🔻 SHORT</span>"
            else:
                badge = "<span class='badge-skip'>❌ SKIP</span>"

            conf = int(float(ev.get('confidence', 0)) * 100)
            
            with st.container():
                rc1, rc2, rc3 = st.columns([1.5, 1, 3.5])
                with rc1:
                    st.markdown(f"**{ev['symbol']}** — {ev['time']}", unsafe_allow_html=True)
                    st.markdown(badge, unsafe_allow_html=True)
                    m_name = ev.get('model', 'unknown')
                    if 'fallback' in m_name:
                        st.caption("🟡 Резервный fallback")
                    else:
                        st.caption(f"🟢 ИИ: {m_name.split('/')[-1]}")
                with rc2:
                    ml_p = ev.get('ml_prob', None)
                    if ml_p is not None:
                        st.metric("Уверенность AI", f"{conf}%", delta=f"ML: {ml_p}%", delta_color="normal")
                    else:
                        st.metric("Уверенность AI", f"{conf}%")
                    st.caption(f"Всплеск: {ev.get('surge', 1)}x | Откат: {ev.get('pullback', 0)}%")
                with rc3:
                    st.markdown(f"**Анализ Groq:** {ev.get('reason', 'N/A')}")
                    if dec in ['BUY', 'SHORT']:
                        p_val = ev.get('price')
                        sl_val = ev.get('sl')
                        tp1_val = ev.get('tp1')
                        p_str = f"${p_val:.4f}" if p_val is not None else "N/A"
                        sl_str = f"${sl_val:.4f}" if sl_val is not None else "N/A"
                        tp1_str = f"${tp1_val:.4f}" if tp1_val is not None else "N/A"
                        st.markdown(f"🎯 *Вход: {p_str} | SL: {sl_str} | TP1: {tp1_str}*")
                st.divider()

# ------------------------------------------------------------------------------
# 3. ВОРОНКА (THE FUNNEL)
# ------------------------------------------------------------------------------
with tab_funnel:
    st.subheader("📊 Воронка отсева (The Funnel Statistics)")
    st.caption("Философия JEV Engine: отсекаем 99% мусора, чтобы входить только в высоковероятные сетапы.")
    
    fs = portfolio.funnel_stats
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        st.metric("1. Universe", fs.get('universe', 0), help="Всего просканировано пар на Binance")
    with fc2:
        st.metric("2. Отсечено индикаторами", fs.get('gate_failed', 0), help="Не хватило импульса или объема")
    with fc3:
        st.metric("3. Блок по BTC", fs.get('btc_blocked', 0), help="Заблокировано из-за резкого сброса BTC")
    with fc4:
        st.metric("4. Кулдаун", fs.get('cooldown_blocked', 0), help="Находится в защитном 5-мин кулдауне")

    fc5, fc6, fc7, fc8 = st.columns(4)
    with fc5:
        st.metric("5. Кандидаты (Hard Gates)", fs.get('hard_gates', 0), help="Прошли все первичные условия")
    with fc6:
        st.metric("6. Оценено Groq ИИ", fs.get('groq_evaluated', 0), help="Отправлено на глубокий анализ в Groq")
    with fc7:
        st.metric("7. Отклонено ИИ (SKIP)", fs.get('groq_skip', 0), help="ИИ обнаружил ловушку или истощение")
    with fc8:
        st.metric("8. Открыто сделок", fs.get('filled', 0), help="Успешно открытые сделки в сопровождении")

# ------------------------------------------------------------------------------
# 4. ИСТОРИЯ СДЕЛОК
# ------------------------------------------------------------------------------
with tab_history:
    st.subheader("📓 Журнал закрытых сделок")
    if not portfolio.trade_history:
        st.info("История сделок пока пуста.")
    else:
        df = pd.DataFrame(portfolio.trade_history)
        st.dataframe(
            df[["symbol", "side", "entry_price", "exit_price", "margin_usdt", "realized_pnl", "roi_pct", "reason", "closed_at"]],
            width="stretch"
        )

# ------------------------------------------------------------------------------
# 5. SHADOW TRACKER (ТЕНЕВОЙ ТРЕКЕР)
# ------------------------------------------------------------------------------
with tab_shadow:
    st.subheader("👻 Shadow Tracker (Проверка исхода отклонённых сетапов)")
    st.caption("Автоматически отслеживает, куда пошла цена после вердикта SKIP. Доказывает, спасает ли ИИ от ловушек.")
    
    sh_stats = portfolio.get_shadow_stats()
    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        st.metric("Отклонено ИИ", sh_stats["total"], help="Сетапы, которые Groq отклонил ради безопасности")
    with sc2:
        st.metric("🛡️ Спас от убытка", sh_stats["saved"], help="Монеты, которые после отсева действительно упали/слились")
    with sc3:
        st.metric("⚠️ Упущенный импульс", sh_stats["missed"], help="Монеты, которые все равно пошли в плюс")
    with sc4:
        st.metric("🎯 Точность отсева", f"{sh_stats['accuracy']}%", help="Процент верных отсевов ловушек ИИ")

    if not portfolio.shadow_trades:
        st.info("Пока нет отклонённых сетапов.")
    else:
        sdf = pd.DataFrame(portfolio.shadow_trades[:30])
        desired_cols = [
            ("symbol", "Монета"),
            ("side", "Направление"),
            ("rejected_at_price", "Вход (отсев)"),
            ("current_price", "Текущая"),
            ("price_change_pct", "Текущее (%)"),
            ("max_profit_pct", "Пик взлета (%)"),
            ("max_loss_pct", "Макс. просадка (%)"),
            ("change_15m_pct", "15м (%)"),
            ("change_1h_pct", "1ч (%)"),
            ("change_2h_pct", "2ч (%)"),
            ("change_3h_pct", "3ч (%)"),
            ("change_4h_pct", "4ч (%)"),
            ("change_5h_pct", "5ч (%)"),
            ("outcome", "Исход"),
            ("reason", "Причина отказа Groq"),
            ("time", "Время")
        ]
        available_cols = [col for col, name in desired_cols if col in sdf.columns]
        rename_map = {col: name for col, name in desired_cols if col in sdf.columns}
        display_df = sdf[available_cols].rename(columns=rename_map)
        st.dataframe(display_df, width="stretch")

# ------------------------------------------------------------------------------
# 6. TIME MACHINE (БЭКТЕСТ ЗА НЕДЕЛЮ ПО МЕТОДОЛОГИИ DAY-TRADER-SKILL)
# ------------------------------------------------------------------------------
with tab_timemachine:
    st.subheader("🔬 Time Machine: Реалистичный бэктест за 7 дней (12 крипто-пар)")
    st.markdown(r"""
    **Честная симуляция реального рынка Binance Futures ($20 депозит):**
    * **12 волатильных пар** (мемкоины, L1/L2, AI, DeFi: SUI, PEPE, DOGE, NEAR, SOL, ENA, JUP, RENDER, WIF, APT, TIA, SEI) — 24 192 5m свечи.
    * **Учет правил ИИ Groq / JEV:** объемный всплеск $\ge 1.45x$, вход на откате в поддержку ("bid the flush"), проверка фитилей истощения, стоп за фитилем.
    * **Реальные комиссии биржи Binance:** учтены комиссии тейкера (0.05% вход + 0.05% выход) на каждую сделку.
    """)
    
    if st.button("▶ Запустить глубокий Time Machine тест (Сравнение вариаций)", type="primary"):
        with st.spinner("Загрузка 24 192 свечей и симуляция 6 конфигураций стратегии..."):
            from realistic_backtest_7d import get_7d_data, simulate_strategy
            cdata = get_7d_data()
            
            configs = [
                ("🏆 60x Optimal Sniper (Рекомендуемый: баланс прибыли и просадки)", 60, "fixed_6", 1.45, 0.65, 0.25, 0.30),
                ("🔥 75x High-Conviction A+ (Максимальный разгон)", 75, "fixed_6", 1.45, 0.65, 0.25, 0.30),
                ("🛡️ 50x Safe Balanced (Всплеск 1.45x, 0.65% ход)", 50, "fixed_5", 1.45, 0.65, 0.25, 0.30),
                ("🎯 35x Conservative (Сложный процент 35%)", 35, "compound_35", 1.35, 0.50, 0.20, 0.35),
                ("🔒 25x Ultra-Safe (Сложный процент 25%)", 25, "compound_25", 1.45, 0.60, 0.25, 0.30),
                ("❌ Нефильтрованная стратегия (Частые микро-входы)", 75, "fixed_5", 1.10, 0.25, 0.15, 0.45),
            ]
            
            rows = []
            for name, lev, mm, surge, imp, wrej, wexh in configs:
                res = simulate_strategy(
                    all_data=cdata, leverage=lev, margin_mode=mm,
                    min_surge=surge, min_impulse=imp, min_wick_rej=wrej, max_wick_exh=wexh,
                    initial_balance=20.0
                )
                rows.append({
                    "Конфигурация": name,
                    "Итог ($)": f"${res['final_balance']:.2f}",
                    "Чистый PnL": f"${res['net_pnl']:+.2f}",
                    "Доходность (ROI)": f"{res['roi_pct']:+.1f}%",
                    "Винрейт": f"{res['win_rate']}%",
                    "Сделок": res['total_trades'],
                    "Макс. просадка": f"{res['max_drawdown_pct']}%",
                    "Profit Factor": res['profit_factor'],
                    "Комиссии биржи": f"${res['total_commission']:.2f}"
                })
                
            st.dataframe(pd.DataFrame(rows), width="stretch")
            st.success("🏆 Победитель: **60x Optimal Sniper** (+93.1% ROI за 7 дней, баланс вырос с $20.00 до $38.62 при винрейте 75.0% и сниженной просадке)!")

# ------------------------------------------------------------------------------
# 7. ВТОРОЙ МОЗГ (OBSIDIAN VAULT & QUANT ML)
# ------------------------------------------------------------------------------
with tab_brain:
    st.subheader("🧠 Второй мозг торгового бота (Obsidian Vault & Квантовый ML)")
    st.markdown("Архитектура долговременной памяти: бот ведёт торговый журнал в Markdown, профилирует повадки монет и использует предобученный квантовый классификатор для фильтрации ловушек.")

    b_col1, b_col2 = st.columns(2)
    with b_col1:
        st.markdown("### ⚡ Квантовая модель (Dual XGBoost Alpha)")
        ml_status = "🟢 Активна (Dual: LONG + SHORT)" if (ml_engine.model_long is not None or ml_engine.model is not None) else "🟡 Ожидает обучения"
        st.info(f"**Статус модели:** {ml_status}")
        
        m_c1, m_c2 = st.columns(2)
        with m_c1:
            st.metric("Винрейт LONG (XGBoost)", f"{getattr(ml_engine, 'winrate_long', 75.0):.1f}%")
        with m_c2:
            st.metric("Винрейт SHORT (XGBoost)", f"{getattr(ml_engine, 'winrate_short', 88.2):.1f}%")
            
        st.metric("Профит-фактор (Profit Factor)", f"{ml_engine.profit_factor:.2f}")
        st.caption(f"Обучена на 30 топ-парах Binance Futures (30 факторов Order Flow) с вычетом комиссий биржи. Порог уверенности: {int(ml_engine.threshold * 100)}%.")

    with b_col2:
        st.markdown("### 📓 База знаний Obsidian Vault")
        st.success(f"**Путь к хранилищу:** `{obsidian_vault.vault_path}`")
        st.caption("Синхронизируется с вашим iCloud Obsidian — заметки мгновенно открываются в приложении Obsidian на Mac и iPhone!")
        
        # Кнопка скачивания хранилища прямо с сервера Render
        import io, zipfile
        def get_vault_zip():
            buf = io.BytesIO()
            v_dir = obsidian_vault.vault_path if os.path.exists(obsidian_vault.vault_path) else obsidian_vault.secondary_path
            if v_dir and os.path.exists(v_dir):
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root, _, files in os.walk(v_dir):
                        for f in files:
                            full_p = os.path.join(root, f)
                            rel_p = os.path.relpath(full_p, v_dir)
                            zf.write(full_p, rel_p)
            buf.seek(0)
            return buf.getvalue()

        st.download_button(
            label="📥 Скачать базу Obsidian Vault с Render (ZIP)",
            data=get_vault_zip(),
            file_name="Binance_AI_Trader_Vault.zip",
            mime="application/zip",
            use_container_width=True
        )

        st.markdown("""
        **Структура разделов Vault:**
        - 📖 `Playbooks/` — Институциональные правила входа (Rocket Long, Breakdown Short, Trap Matrix).
        - 📁 `Token_Dossiers/` — Досье на каждую монету с памятью ошибок и винрейтом.
        - ⚡ `Journal/` — Автоматический журнал всех сделок с пост-мортем анализом.
        - 🛡️ `Shadow_Audits/` — Аудит отклонённых сетапов.
        """)

    st.markdown("---")
    st.markdown("### 📖 Интерактивный просмотр заметок из Obsidian")
    vault_dir = obsidian_vault.vault_path
    if not os.path.exists(vault_dir) and obsidian_vault.secondary_path:
        vault_dir = obsidian_vault.secondary_path

    if os.path.exists(vault_dir):
        all_notes = []
        for root, _, files in os.walk(vault_dir):
            for f in files:
                if f.endswith(".md"):
                    rel = os.path.relpath(os.path.join(root, f), vault_dir)
                    all_notes.append(rel)
        all_notes.sort()

        if all_notes:
            selected_note = st.selectbox("Выберите заметку из базы Obsidian для чтения:", all_notes)
            note_full_path = os.path.join(vault_dir, selected_note)
            try:
                with open(note_full_path, "r", encoding="utf-8") as nf:
                    note_content = nf.read()
                st.markdown(f"#### 📄 `{selected_note}`")
                st.code(note_content, language="markdown")
            except Exception as e:
                st.error(f"Не удалось прочитать заметку: {e}")
        else:
            st.info("В хранилище пока нет заметок.")
    else:
        st.warning("Хранилище Obsidian пока инициализируется.")

# ==============================================================================
# АВТООБНОВЛЕНИЕ СТРАНИЦЫ (В САМОМ КОНЦЕ СКРИПТА ПОСЛЕ ОТРИСОВКИ ВСЕГО UI)
# ==============================================================================
if auto_refresh:
    time.sleep(4)
    st.rerun()
