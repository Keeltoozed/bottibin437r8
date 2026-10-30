import sys
import os

# Гарантируем немедленный вывод логов на Render / Docker (без буферизации)
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
    st.text(f"Маржа на сделку: ${config.TRADE_AMOUNT_USDT:.1f}")
    st.text(f"Плечо: {config.LEVERAGE}x")
    st.text(f"Макс. позиций: {config.MAX_CONCURRENT_POSITIONS}")
    st.text(f"Модель Groq: {config.GROQ_PRIMARY_MODEL}")
    
    st.divider()
    if st.button("🔄 Сбросить портфель к $20.00"):
        portfolio.cash = config.INITIAL_BALANCE
        portfolio.open_positions.clear()
        portfolio.trade_history.clear()
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
st.caption(f"Автономный торговый конвейер: Сканер Binance Futures → Groq Soft Gate → Dynamic Breakeven & Stop Under Wick | Режим: {'🧪 Paper Trading (Симуляция)' if config.PAPER_TRADING else '⚡ Live Trading'} | Последний скан: {last_scan_info}")

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
tab_pos, tab_radar, tab_funnel, tab_history, tab_shadow = st.tabs([
    "🟢 Открытые позиции",
    "🤖 Groq Live Radar",
    "📊 Воронка The Funnel",
    "📓 История сделок",
    "👻 Shadow Tracker"
])

# ------------------------------------------------------------------------------
# 1. ОТКРЫТЫЕ ПОЗИЦИИ
# ------------------------------------------------------------------------------
with tab_pos:
    st.subheader("🟢 Активные сделки в сопровождении")
    if not portfolio.open_positions:
        st.info("В данный момент нет открытых сделок. Автономный сканер ищет пробойные сетапы...")
    else:
        for sym, pos in list(portfolio.open_positions.items()):
            with st.container():
                pnl_color = "#3fb950" if pos['unrealized_pnl'] >= 0 else "#f85149"
                be_badge = "🛡️ Безубыток АКТИВЕН" if pos['breakeven_set'] else "Ожидание TP1"
                
                col_a, col_b, col_c, col_d, col_e = st.columns([2, 2, 2, 2, 1])
                with col_a:
                    st.markdown(f"### {sym} <span class='badge-long'>{pos['side']} {pos['leverage']}x</span>", unsafe_allow_html=True)
                    st.caption(f"Вход: **${pos['entry_price']:.4f}** | Маржа: **${pos['margin_usdt']:.2f}**")
                with col_b:
                    st.metric("Текущая цена", f"${pos['current_price']:.4f}")
                with col_c:
                    st.metric("PnL (%)", f"{pos['pnl_pct']:+.2f}%", delta=f"${pos['unrealized_pnl']:+.2f}")
                with col_d:
                    st.markdown(f"**Stop Under Wick:** `${pos['wick_sl']:.4f}`")
                    st.markdown(f"**TP1:** `${pos['tp1']:.4f}` | **TP2:** `${pos['tp2']:.4f}`")
                    st.caption(be_badge)
                with col_e:
                    if st.button("Закрыть", key=f"close_{sym}"):
                        portfolio.close_position(sym, pos['current_price'], "Ручное закрытие из интерфейса")
                        st.rerun()
                st.caption(f"🧠 Логика Groq: {pos.get('groq_reason', 'N/A')}")
                st.divider()

# ------------------------------------------------------------------------------
# 2. GROQ LIVE RADAR (ОЦЕНКА МОНЕТ)
# ------------------------------------------------------------------------------
with tab_radar:
    st.subheader("🤖 Живой радар Groq (Оценки сетапов в реальном времени)")
    st.caption("Каждые несколько секунд бот опрашивает Groq через JEV Engine. Здесь отображается вердикт и объяснение AI.")
    
    if not portfolio.recent_evaluations:
        st.info("Ожидание первых данных от сканера...")
    else:
        for ev in portfolio.recent_evaluations[:15]:
            badge = "<span class='badge-buy'>✅ BUY / APPROVED</span>" if ev['decision'] == 'BUY' else "<span class='badge-skip'>❌ SKIP / REJECTED</span>"
            conf = int(float(ev.get('confidence', 0)) * 100)
            
            with st.container():
                rc1, rc2, rc3 = st.columns([1.5, 1, 3.5])
                with rc1:
                    st.markdown(f"**{ev['symbol']}** — {ev['time']}", unsafe_allow_html=True)
                    st.markdown(badge, unsafe_allow_html=True)
                with rc2:
                    st.metric("Уверенность AI", f"{conf}%")
                    st.caption(f"Всплеск: {ev.get('surge', 1)}x | Откат: {ev.get('pullback', 0)}%")
                with rc3:
                    st.markdown(f"**Анализ Groq:** {ev.get('reason', 'N/A')}")
                    if ev['decision'] == 'BUY':
                        st.markdown(f"🎯 *Вход: ${ev.get('price'):.4f} | Wick SL: ${ev.get('sl'):.4f} | TP1: ${ev.get('tp1'):.4f}*")
                st.divider()

# ------------------------------------------------------------------------------
# 3. ВОРОНКА (THE FUNNEL)
# ------------------------------------------------------------------------------
with tab_funnel:
    st.subheader("📊 Воронка отсева (The Funnel Statistics)")
    st.caption("Философия JEV Engine: отсекаем 99% мусора, чтобы входить только в высоковероятные сетапы.")
    
    fs = portfolio.funnel_stats
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
    with fc1:
        st.metric("1. Universe", fs['universe'], help="Всего просканировано пар на Binance")
    with fc2:
        st.metric("2. Hard Gates", fs['hard_gates'], help="Прошли фильтр 24ч объема, спреда и волатильности")
    with fc3:
        st.metric("3. Groq Evaluated", fs['groq_evaluated'], help="Отправлено на глубокий анализ в Groq")
    with fc4:
        st.metric("4. Groq Approved", fs['passed'], help="Одобрено AI с уверенностью >= 65%")
    with fc5:
        st.metric("5. Filled (Входы)", fs['filled'], help="Успешно открытые сделки")

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
            use_container_width=True
        )

# ------------------------------------------------------------------------------
# 5. SHADOW TRACKER (ТЕНЕВОЙ ТРЕКЕР)
# ------------------------------------------------------------------------------
with tab_shadow:
    st.subheader("👻 Shadow Tracker (Отклонённые сетапы)")
    st.caption("Монеты, которые бот отфильтровал. Позволяет проверить качество работы AI-фильтров.")
    if not portfolio.shadow_trades:
        st.info("Пока нет отклонённых сетапов.")
    else:
        st.dataframe(pd.DataFrame(portfolio.shadow_trades[:30]), use_container_width=True)

# ==============================================================================
# АВТООБНОВЛЕНИЕ СТРАНИЦЫ (В САМОМ КОНЦЕ СКРИПТА ПОСЛЕ ОТРИСОВКИ ВСЕГО UI)
# ==============================================================================
if auto_refresh:
    time.sleep(4)
    st.rerun()
