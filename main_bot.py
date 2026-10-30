import asyncio
import os
import sys
import time
from binance_client import binance_client
from scanner import market_scanner
from exit_manager import exit_manager
from tracker import portfolio
import config

async def start_autonomous_bot():
    """
    Запуск автономного конвейера:
      1. Сканер рынка Binance Futures (Universe -> Hard Gates -> Groq AI Gate)
      2. Менеджер выхода (Dynamic Breakeven, Stop under Wick, Multi-tier TP, Trailing)
    """
    print("=" * 70)
    print("🚀 BINANCE AUTONOMOUS GROQ TRADER (JEV ENGINE)")
    print(f"💰 Стартовый банкролл: ${portfolio.cash:.2f} USDT")
    print(f"🎯 Размер сделки: ${config.TRADE_AMOUNT_USDT:.2f} USDT | Плечо: {config.LEVERAGE}x")
    print(f"🤖 Groq Модель: {config.GROQ_PRIMARY_MODEL}")
    print(f"🧪 Режим: {'PAPER TRADING (Симуляция на реальных котировках)' if config.PAPER_TRADING else 'LIVE TRADING'}")
    print("=" * 70)

    try:
        await asyncio.gather(
            market_scanner.run_loop(),
            exit_manager.run_loop()
        )
    except asyncio.CancelledError:
        print("🛑 Фоновый бот остановлен.")
    finally:
        await binance_client.close()

def run_in_background():
    """Запуск в отдельном потоке (для Streamlit / Web UI)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_autonomous_bot())
    except Exception as e:
        print(f"⚠️ Ошибка в фоновом потоке бота: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(start_autonomous_bot())
    except KeyboardInterrupt:
        print("\nОстановка по запросу пользователя.")

