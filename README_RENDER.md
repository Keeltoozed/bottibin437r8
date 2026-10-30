# 🚀 Binance Autonomous Groq Trader (JEV Engine)

Автономный торговый бот для **Binance Futures** с искусственным интеллектом **Groq (JEV Engine)**, веб-интерфейсом **Streamlit** и полной поддержкой деплоя на **Render.com**.

---

## 🧠 Ключевые фишки и архитектура

1. **Автономный сканер рынка (The Funnel)**:
   - Непрерывно сканирует пары Binance Futures по объему, спреду в стакане и импульсу.
   - Отсекает 99% мусора через **Hard Gates** (24h объем > $15M, всплеск объема 5m > 1.6x, спред < 0.1%).
2. **Groq AI Gate (JEV Engine)**:
   - Анализирует каждый кандидат через бесплатный сверхбыстрый API Groq (`openai/gpt-oss-120b`).
   - Правило **"We bid the flush, not the candle"**: бот никогда не покупает на вершине зеленой свечи, а входит строго на локальном микро-откате в поддержку.
   - Правило **"The stop lives under the wick"**: расчет плотного стоп-лосса точно под нижний фитиль свечи отката.
   - Фильтр **"Momentum already spent"**: отсекает истощенные движения с риском резкого дампа.
3. **Менеджер умного выхода (Exit Manager)**:
   - **Dynamic Breakeven**: при прохождении 50% пути к TP1 стоп-лосс автоматически переносится в безубыток (+0.1%).
   - **Tiered Take-Profit**:
     - **TP1 (+2.2%)**: фиксация 50% объема и гарантированный безубыток на остаток.
     - **TP2 (+4.5%)**: фиксация еще 25% объема.
     - **Остаток 25%**: трейлинг-стоп за локальным максимумом (ATH).
4. **Режим Paper Trading ($20 Bankroll)**:
   - Стартовый баланс $20.00.
   - Маржа на сделку $5.00 с плечом 5x (позиция $25), что позволяет держать до 3 одновременных сделок.
   - Все расчеты и котировки идут по реальным тикерам и стаканам Binance.

---

## 💻 Локальный запуск на компьютере

Для запуска веб-дашборда и фонового бота выполните в терминале:

```bash
./start.sh
```
или
```bash
streamlit run app.py
```

Веб-панель откроется в браузере по адресу: `http://localhost:8501`.

---

## ☁️ Деплой на Render.com (Шаг за шагом)

1. Загрузите файлы репозитория на свой GitHub.
2. Откройте [Render.com](https://dashboard.render.com/) и нажмите **New + → Web Service**.
3. Подключите ваш GitHub репозиторий.
4. Задайте настройки:
   - **Name**: `binance-groq-bot`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
   - **Plan**: `Free`
5. В разделе **Environment Variables** (Переменные окружения) добавьте:
   - `GROQ_API_KEY` = (ваш ключ Groq из файла .env)
   - `PAPER_TRADING` = `true`
   - `INITIAL_BALANCE` = `20.0`
   - `TRADE_AMOUNT_USDT` = `5.0`
   - `LEVERAGE` = `5`
   - `MAX_POSITIONS` = `3`
   - `BINANCE_API_KEY` = (ваш ключ Binance)
   - `BINANCE_SECRET` = (ваш секрет Binance)
6. Нажмите **Deploy Web Service**.
   Через 2–3 минуты Render соберет проект и выдаст публичную ссылку на ваш веб-интерфейс (`https://ваш-бот.onrender.com`).

