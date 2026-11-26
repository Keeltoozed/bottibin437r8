#!/bin/bash
# Автономный запуск торгового бота + Streamlit дашборда в едином процессе (бот стартует сразу на 0-й секунде!)
export PORT=${PORT:-8501}
echo "🚀 Запуск Alpha Rocket Hunter (boot.py) на порту $PORT..."
exec python3 -u boot.py
