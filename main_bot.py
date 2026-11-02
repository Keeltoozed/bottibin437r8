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
from binance_client import binance_client
from scanner import market_scanner
from exit_manager import exit_manager
from tracker import portfolio
import config

async def heartbeat_loop():
    """Периодический отчет в логи каждые 30 секунд."""
    while True:
        try:
            summary = portfolio.get_portfolio_summary()
            live_u = getattr(portfolio, "last_universe_count", 0)
            mirror_tag = binance_client.active_mirror_name
            print(
                f"💓 [HEARTBEAT] Бот активен [{mirror_tag}] | Equity: ${summary['equity']:.2f} (Cash: ${summary['cash']:.2f}) | "
                f"Позиций: {summary['open_positions_count']}/{summary['max_positions']} | "
                f"Радар: {live_u} пар (всего проходов: {portfolio.funnel_stats['universe']}) | "
                f"Оценок Groq: {portfolio.funnel_stats['groq_evaluated']}",
                flush=True
            )
        except Exception as e:
            print(f"⚠️ Ошибка в heartbeat: {e}", flush=True)
        await asyncio.sleep(30)

async def start_autonomous_bot():
    """
    Запуск автономного конвейера Structural Rocket Hunter:
      1. Сканер пробоев (200+ ликвидных пар Binance -> 20-бар пробой + 15m MTF Guard + RVOL >= 1.8x -> ML + Groq AI)
      2. Асимметричный менеджер выхода (30% 1.5R / 30% 3R / 40% ATR Трейл + 18m Скретч + 35m Time-Stop)
      3. Heartbeat-монитор
    """
    print("=" * 70, flush=True)
    print("🚀 BINANCE AUTONOMOUS GROQ TRADER (STRUCTURAL ROCKET HUNTER 200+ UNIVERSE)", flush=True)
    print(f"💰 Стартовый банкролл: ${portfolio.cash:.2f} USDT", flush=True)
    risk_pct = getattr(config, "RISK_PER_TRADE_PCT", 0.025) * 100.0
    est_1r = portfolio.cash * getattr(config, "RISK_PER_TRADE_PCT", 0.025)
    leverage_val = getattr(config, "LEVERAGE", 12)
    groq_model = getattr(config, "GROQ_PRIMARY_MODEL", "openai/gpt-oss-120b")
    paper_mode = getattr(config, "PAPER_TRADING", True)
    print(f"🎯 Фиксированный риск 1R: {risk_pct:.1f}% (~${est_1r:.2f}) | Плечо: {leverage_val}x | Макс позиций: {config.MAX_CONCURRENT_POSITIONS}", flush=True)
    print(f"📡 Радар рынка: до {config.SCAN_TICKERS_LIMIT} пар (24h Volume + 15m MTF Guard + RVOL >= {config.MIN_5M_VOLUME_SURGE_RATIO}x)", flush=True)
    print(f"🤖 Groq Модель: {groq_model}", flush=True)
    print(f"🧪 Режим: {'PAPER TRADING (Симуляция на реальных котировках)' if paper_mode else 'LIVE TRADING'}", flush=True)
    print("=" * 70, flush=True)

    try:
        await asyncio.gather(
            market_scanner.run_loop(),
            exit_manager.run_loop(),
            heartbeat_loop()
        )
    except asyncio.CancelledError:
        print("🛑 Фоновый бот остановлен.", flush=True)
    finally:
        await binance_client.close()

def run_in_background():
    """Запуск в отдельном потоке (для Streamlit / Web UI)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_autonomous_bot())
    except Exception as e:
        print(f"⚠️ Ошибка в фоновом потоке бота: {e}", flush=True)

if __name__ == "__main__":
    try:
        asyncio.run(start_autonomous_bot())
    except KeyboardInterrupt:
        print("\nОстановка по запросу пользователя.", flush=True)
