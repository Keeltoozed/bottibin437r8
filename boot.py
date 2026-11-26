import os
import sys
import threading

# Гарантируем немедленный вывод логов в Render / Docker
os.environ["PYTHONUNBUFFERED"] = "1"
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass


def main():
    """
    Единая точка входа для Render / VPS / Локального запуска:
    1. Мгновенно запускает автономного торгового бота в фоне на 0-й секунде старта сервера —
       бот работает 24/7 даже БЕЗ открытой вкладки браузера и при пробуждении по HTTP-пингу!
    2. В этом же процессе поднимает веб-дашборд Streamlit (общий объект portfolio в памяти,
       нулевая задержка синхронизации, все кнопки управления работают мгновенно).
    """
    from main_bot import run_in_background

    os.environ["BOT_ALREADY_STARTED"] = "1"
    bot_thread = threading.Thread(target=run_in_background, daemon=True, name="AutonomousTraderBot")
    bot_thread.start()
    print("🚀 [BOOT] Автономный торговый бот запущен при старте сервера (независимо от браузера)!", flush=True)

    port = str(os.getenv("PORT", "8501"))
    sys.argv = [
        "streamlit",
        "run",
        "app.py",
        "--server.port", port,
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
    ]
    from streamlit.web import cli as stcli
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()

