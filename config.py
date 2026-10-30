import os
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# 1. GROQ AI ENGINE CONFIG (JEV ENGINE)
# ==============================================================================
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")
GROQ_PRIMARY_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()
GROQ_FALLBACK_MODEL = os.getenv("GROQ_MODEL_FALLBACK", "openai/gpt-oss-20b").strip()
GROQ_RPM_LIMIT = int(os.getenv("GROQ_RPM_LIMIT", "25"))  # Safe rate limit for free tier (max 30 RPM)
GROQ_MIN_CONFIDENCE = float(os.getenv("GROQ_MIN_CONFIDENCE", "0.75"))  # Повышен порог для отсева мусора (только A+ сетапы)

# Институциональные фильтры входа (High-Conviction A+ Scanners)
MIN_VOLUME_SURGE = float(os.getenv("MIN_VOLUME_SURGE", "1.30"))  # Всплеск объема от 1.3x к средней
MIN_IMPULSE_PCT = float(os.getenv("MIN_IMPULSE_PCT", "0.45"))    # Импульс свечи от 0.45%
MIN_RSI_LONG = 40.0
MAX_RSI_LONG = 70.0
MIN_RSI_SHORT = 30.0
MAX_RSI_SHORT = 60.0

# ==============================================================================
# 2. BINANCE API CONFIG
# ==============================================================================
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_SECRET = (os.getenv("BINANCE_SECRET") or "").strip()
USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"

# Endpoints
BINANCE_FUTURES_PUBLIC_URL = "https://fapi.binance.com"
BINANCE_TESTNET_FUTURES_URL = "https://testnet.binancefuture.com"

# ==============================================================================
# 3. TRADING & RISK MANAGEMENT (DAY-TRADER-SKILL 2R/3R DISCIPLINE)
# ==============================================================================
# Paper trading is enabled by default for safe real-market testing
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "20.0"))

# Дисциплина Day-Trader-Skill: динамический сложный процент (Compounding)
# При росте баланса размер риска и прибыль растут автоматически!
ENABLE_COMPOUNDING = os.getenv("ENABLE_COMPOUNDING", "true").lower() == "true"
COMPOUND_RISK_PCT = float(os.getenv("COMPOUND_RISK_PCT", "0.05"))  # 5% от депозита на сделку ($1 при $20, $5 при $100)
MAX_RISK_PER_TRADE_USD = float(os.getenv("MAX_RISK_PER_TRADE_USD", "0.80")) # минимум $0.80
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "6.00"))  # Дневной лимит убытка ($6.00 = 30% счета)
TARGET_1_R = 2.0  # Цель 1: 2R (+10% к балансу)
TARGET_2_R = 3.5  # Цель 2: 3.5R (+17.5% к балансу)
ENABLE_SHORT = os.getenv("ENABLE_SHORT", "true").lower() == "true"  # Торговля в LONG и SHORT

# Для капитала $20: $6 маржа на сделку (2 сделки = $12 в работе, $8 свободный резерв)
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "6.0"))
LEVERAGE = 60  # Значение по умолчанию: 60x (Оптимальный баланс высокой прибыли и сниженной просадки)
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_POSITIONS", "2"))

# ==============================================================================
# 4. EXIT STRATEGY & "THE LINE" (GROK x JEV RULES DEDICATED FOR 60x LEVERAGE)
# ==============================================================================
# "We bid the flush, not the candle": pullback required before entry
MIN_PULLBACK_PCT = float(os.getenv("MIN_PULLBACK_PCT", "0.002"))  # 0.2% pullback

# "The stop lives under the wick": ultra-tight wick buffer for 60x leverage
WICK_BUFFER_PCT = float(os.getenv("WICK_BUFFER_PCT", "0.001"))
MAX_ALLOWED_SL_PCT = float(os.getenv("MAX_ALLOWED_SL_PCT", "0.012"))  # Макс. 1.2% SL (защита от ликвидации на 60x)

# Multi-tier Take Profit (с плечом 60x):
# +1.5% ход цены = +90.0% ROI (TP1: фиксация 50% + мгновенный безубыток)
# +3.0% ход цены = +180.0% ROI (TP2: фиксация 25%)
# Остаток 25%: трейлинг-стоп 0.8%
TP1_PCT = float(os.getenv("TP1_PCT", "0.015"))
TP2_PCT = float(os.getenv("TP2_PCT", "0.030"))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.008"))  # 0.8% trailing

# Быстрый перевод в безубыток при прохождении 40% пути до TP1 (+0.6% ход = +45% прибыли)
BREAKEVEN_TRIGGER_RATIO = 0.40

# Momentum Death: early exit if 1m volume collapses and price stalls
ENABLE_MOMENTUM_DEATH_EXIT = True

# ==============================================================================
# 5. MARKET SCANNER & THE FUNNEL (EXPANDED RADAR: 200+ TOKENS)
# ==============================================================================
# Фильтр ликвидности: только топовые монеты с объемом от $15M в сутки (исключаем неликвидный мусор)
MIN_24H_VOLUME_USDT = float(os.getenv("MIN_24H_VOLUME_USDT", "15000000"))  # $15M
MIN_5M_VOLUME_SURGE_RATIO = float(os.getenv("MIN_5M_VOLUME_SURGE_RATIO", "1.50"))  # 1.50x реальный всплеск объёма
MIN_5M_PRICE_IMPULSE_PCT = float(os.getenv("MIN_5M_PRICE_IMPULSE_PCT", "0.55"))  # 0.55% четкий импульс свечи (отсекает сонные боковики)
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.0015"))  # 0.15% max spread
SCAN_TICKERS_LIMIT = int(os.getenv("SCAN_TICKERS_LIMIT", "100"))  # Сканируем топ-100 волатильных пар
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "10"))
PAIR_COOLDOWN_MINUTES = int(os.getenv("PAIR_COOLDOWN_MINUTES", "5"))

# ==============================================================================
# 6. TELEGRAM NOTIFICATIONS (FAIL-SAFE OPTIONAL)
# ==============================================================================
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
ENABLE_TELEGRAM = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# ==============================================================================
# 7. SERVER / RENDER SETTINGS
# ==============================================================================
PORT = int(os.getenv("PORT", "8501"))
RENDER = bool(os.getenv("RENDER"))

