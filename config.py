import os
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# 1. GROQ AI ENGINE CONFIG (JEV ENGINE)
# ==============================================================================
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")
GROQ_PRIMARY_MODEL = os.getenv("GROQ_MODEL", "allam-2-7b").strip()
GROQ_FALLBACK_MODEL = os.getenv("GROQ_MODEL_FALLBACK", "openai/gpt-oss-120b").strip()
GROQ_RPM_LIMIT = int(os.getenv("GROQ_RPM_LIMIT", "25"))  # Safe rate limit for free tier (max 30 RPM)
GROQ_MIN_CONFIDENCE = float(os.getenv("GROQ_MIN_CONFIDENCE", "0.75"))  # Повышен порог для отсева мусора (только A+ сетапы)

# Институциональные фильтры входа (High-Conviction A+ Scanners)
# Отсекаем вялый боковик: всплеск объема строго от 1.50x, чистый импульс от 0.40%
MIN_VOLUME_SURGE = float(os.getenv("MIN_VOLUME_SURGE", "1.50"))  # Всплеск объема от 1.50x
MIN_IMPULSE_PCT = float(os.getenv("MIN_IMPULSE_PCT", "0.40"))    # Импульс свечи от 0.40%
MIN_RSI_LONG = 35.0
MAX_RSI_LONG = 75.0
MIN_RSI_SHORT = 25.0
MAX_RSI_SHORT = 65.0

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
COMPOUND_RISK_PCT = float(os.getenv("COMPOUND_RISK_PCT", "0.08"))  # 8% от депозита на сделку ($1.60 при $20)
MAX_RISK_PER_TRADE_USD = float(os.getenv("MAX_RISK_PER_TRADE_USD", "1.00")) # минимум $1.00

# Институциональный предохранитель депозита (Circuit Breaker):
ENABLE_CIRCUIT_BREAKER = True
MAX_CONSECUTIVE_LOSSES = 2  # Пауза после 2 стопов подряд для защиты от распила в боковике
CONSECUTIVE_LOSS_PAUSE_SECONDS = 3600  # 60 минут паузы
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "4.00"))  # Макс $4 дневного убытка (20% от $20)

TARGET_1_R = 2.0  # Цель 1: 2R
TARGET_2_R = 3.5  # Цель 2: 3.5R
ENABLE_SHORT = os.getenv("ENABLE_SHORT", "true").lower() == "true"  # Торговля в LONG и SHORT

# ОПТИМАЛЬНОЕ ПЛЕЧО ДЛЯ СКАЛЬПИНГА КРИПТЫ: 30x
# 1. Режет биржевые комиссии Binance в 2 раза по сравнению с 60x!
# 2. Позволяет стоп-лоссу дышать на 1.0%..1.2% под фитилем без риска мгновенной ликвидации
LEVERAGE = int(os.getenv("LEVERAGE", "30"))
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_POSITIONS", "2"))

# ==============================================================================
# 4. EXIT STRATEGY & "THE LINE" (INSTITUTIONAL DAY-TRADING DISCIPLINE)
# ==============================================================================
MIN_PULLBACK_PCT = float(os.getenv("MIN_PULLBACK_PCT", "0.0010"))
WICK_BUFFER_PCT = float(os.getenv("WICK_BUFFER_PCT", "0.0010"))
MAX_ALLOWED_SL_PCT = float(os.getenv("MAX_ALLOWED_SL_PCT", "0.0125"))  # Макс. 1.25% SL (безопасно для 30x)

# Multi-tier Take Profit (с плечом 30x):
# +1.5% ход цены = +45.0% ROI (TP1: фиксация 50% + мгновенный безубыток с плюсом)
# +3.0% ход цены = +90.0% ROI (TP2: фиксация 25%)
# Остаток 25%: динамический трейлинг-стоп 0.8%
TP1_PCT = float(os.getenv("TP1_PCT", "0.015"))
TP2_PCT = float(os.getenv("TP2_PCT", "0.030"))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.008"))  # 0.8% trailing

# ==============================================================================
# 5. MARKET SCANNER & ELITE HIGH-LIQUIDITY UNIVERSE
# ==============================================================================
# Строго топ-ликвидные активы с глубоким стаканом (исключает манипулятивный мусор вроде BMT, NIL, GTC)
MIN_24H_VOLUME_USDT = float(os.getenv("MIN_24H_VOLUME_USDT", "35000000"))  # $35M минимум
SCAN_TICKERS_LIMIT = int(os.getenv("SCAN_TICKERS_LIMIT", "45"))
STRICT_WHITELIST_ONLY = True  # СТРОГО топ-проверенные активы!
CHOP_MIN_VOLUME_SURGE = 2.50  # В боковике BTC требуем взрывной объем от 2.5x для входа!
ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.68"))

# Элитный юниверс криптовалют (только топ-ликвидность и институциональные пары)
TOP_CRYPTO_UNIVERSE = [
    # Топ мажоры и L1 лидеры
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "AVAXUSDT", "SUIUSDT",
    # Топ L1/L2 инфраструктура с глубоким стаканом
    "NEARUSDT", "LINKUSDT", "APTUSDT", "RENDERUSDT", "TIAUSDT", "SEIUSDT", "ENAUSDT", "JUPUSDT", "INJUSDT", "AAVEUSDT",
    "DOTUSDT", "LTCUSDT", "BCHUSDT", "OPUSDT", "ARBUSDT", "FILUSDT", "STXUSDT", "ONDOUSDT", "WLDUSDT", "TAOUSDT", "TONUSDT",
    # Высоколиквидные мемкоины (стакан от $20M+)
    "PEPEUSDT", "1000PEPEUSDT", "WIFUSDT", "SHIBUSDT", "BONKUSDT", "FLOKIUSDT", "BOMEUSDT", "POPCATUSDT",
    # Топ DeFi & AI
    "FETUSDT", "UNIUSDT", "PENDLEUSDT", "GALAUSDT", "SANDUSDT", "DYDXUSDT", "LDOUSDT", "RAYUSDT"
]

# Черный список: стейблкоины, фиат, хаки и синтетические акции
EXCLUDED_TICKERS = {
    # Стейблкоины и фиат
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "EURUSDT", "DAIUSDT", "USTCUSDT", "PAXGUSDT", "XAUUSDT", "XAGUSDT",
    # Традиционные акции и ETF
    "GOOGLUSDT", "MSTRUSDT", "QQQUSDT", "MUUSDT", "SOXSUSDT", "SPYUSDT", "NVDAUSDT", 
    "TSLAUSDT", "AAPLUSDT", "AMZNUSDT", "MSFTUSDT", "COINBUSDT", "SOXLUSDT", "INTCUSDT", "SNDKUSDT",
    "SKHYNIXUSDT", "SKHYUSDT", "KORUUSDT", "SPCXUSDT", "AKEUSDT", "CRCLUSDT",
    # Хакнутые/проблемные токены
    "INITUSDT", "CRVUSDT", "MEGAUSDT", "AVAUSDT", "SOLVUSDT", "BIRBUSDT"
}
MIN_5M_VOLUME_SURGE_RATIO = float(os.getenv("MIN_5M_VOLUME_SURGE_RATIO", "1.50"))  # 1.50x реальный всплеск объёма
MIN_5M_PRICE_IMPULSE_PCT = float(os.getenv("MIN_5M_PRICE_IMPULSE_PCT", "0.55"))  # 0.55% четкий импульс свечи (отсекает сонные боковики)
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.0015"))  # 0.15% max spread
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

