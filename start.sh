#!/bin/bash
# Запуск автономного торгового бота Binance + Groq с веб-интерфейсом Streamlit
PORT=${PORT:-8501}
echo "🚀 Запуск Binance Autonomous Groq Trader на порту $PORT..."
streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true

