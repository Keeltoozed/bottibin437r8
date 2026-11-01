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
            print(
                f"💓 [HEARTBEAT] Бот активен | Баланс: ${summary['cash']:.2f} | "
                f"Открытых позиций: {summary['open_positions_count']}/{summary['max_positions']} | "
                f"Просканировано пар: {portfolio.funnel_stats['universe']} | "
                f"Оценок Groq: {portfolio.funnel_stats['groq_evaluated']}",
                flush=True
            )
        except Exception as e:
            print(f"⚠️ Ошибка в heartbeat: {e}", flush=True)
        await asyncio.sleep(30)

async def start_autonomous_bot():
    """
    Запуск автономного конвейера:
      1. Сканер рынка Binance Futures (Universe -> Hard Gates -> Groq AI Gate)
      2. Менеджер выхода (Dynamic Breakeven, Stop under Wick, Multi-tier TP, Trailing)
      3. Heartbeat-монитор
    """
    print("=" * 70, flush=True)
    print("🚀 BINANCE AUTONOMOUS GROQ TRADER (JEV ENGINE)", flush=True)
    print(f"💰 Стартовый банкролл: ${portfolio.cash:.2f} USDT", flush=True)
    trade_amount = getattr(config, "TRADE_AMOUNT_USDT", 5.0)
    leverage_val = getattr(config, "LEVERAGE", 30)
    groq_model = getattr(config, "GROQ_PRIMARY_MODEL", "allam-2-7b")
    paper_mode = getattr(config, "PAPER_TRADING", True)
    print(f"🎯 Размер сделки: ${trade_amount:.2f} USDT | Плечо: {leverage_val}x", flush=True)
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
