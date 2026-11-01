import os
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# 1. GROQ AI ENGINE CONFIG (JEV ENGINE)
# ==============================================================================
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")
GROQ_PRIMARY_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
GROQ_FALLBACK_MODEL = os.getenv("GROQ_MODEL_FALLBACK", "openai/gpt-oss-20b").strip()
GROQ_RPM_LIMIT = int(os.getenv("GROQ_RPM_LIMIT", "25"))  # Безопасный лимит Groq Free Tier (до 30 RPM)
GROQ_MIN_CONFIDENCE = float(os.getenv("GROQ_MIN_CONFIDENCE", "0.65"))  # 65% минимальная уверенность ИИ для подтверждения сделки

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
# 3. TRADING & RISK MANAGEMENT (SELECTIVE A+ DAY-TRADER BACKTEST ENGINE)
# ==============================================================================
# Paper trading is enabled by default for safe real-market testing
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "20.0"))

# Фиксированная скальперская маржа $4.00 (контроль риска 1-2% депозита):
# При депозите $20 и плече 10x стоп 0.8% стоит всего -$0.32 (1.6% депозита вместо сливных 15-25% при 50x)
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "4.0"))
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_POSITIONS", "2"))  # Строго максимум 2 позиции одновременно

# Институциональный предохранитель депозита (Circuit Breaker):
# Максимум 3 убытка в день (UTC). После 3 стопов бот останавливает торговлю до завтра!
DAILY_LOSS_LIMIT = int(os.getenv("DAILY_LOSS_LIMIT", "3"))
ENABLE_CIRCUIT_BREAKER = True
MAX_CONSECUTIVE_LOSSES = 2
CONSECUTIVE_LOSS_PAUSE_SECONDS = 3600
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "2.00"))

TARGET_1_R = 2.0  # Цель 1: 2R
TARGET_2_R = 3.5  # Цель 2: 3.5R
ENABLE_SHORT = os.getenv("ENABLE_SHORT", "true").lower() == "true"  # Торговля в LONG и SHORT

# АДЕКВАТНОЕ КРЕДИТНОЕ ПЛЕЧО ДЛЯ СКАЛЬПИНГА КРИПТЫ: 10x (1-2% риск на сделку)
LEVERAGE = int(os.getenv("LEVERAGE", "10"))

# Селективные скальперские фильтры входа (Breakout-Pullback на закрытых свечах):
MIN_5M_VOLUME_SURGE_RATIO = float(os.getenv("MIN_5M_VOLUME_SURGE_RATIO", "1.25"))  # Всплеск объема закрытой свечи от 1.25x
MIN_5M_PRICE_IMPULSE_PCT = float(os.getenv("MIN_5M_PRICE_IMPULSE_PCT", "0.45"))    # Чистый импульс закрытой свечи от 0.45%
WICK_REJECTION_MIN = float(os.getenv("WICK_REJECTION_MIN", "0.12"))                # Защитный фитиль отбоя не менее 12% свечи
WICK_EXHAUSTION_MAX = float(os.getenv("WICK_EXHAUSTION_MAX", "0.38"))              # Встречный фитиль истощения не более 38% свечи
STOP_LOSS_MIN_PCT = float(os.getenv("STOP_LOSS_MIN_PCT", "0.004"))                  # 0.4% мин стоп
STOP_LOSS_MAX_PCT = float(os.getenv("STOP_LOSS_MAX_PCT", "0.012"))                  # 1.2% макс стоп

# ==============================================================================
# 4. EXIT STRATEGY & "THE LINE" (INSTITUTIONAL DAY-TRADING DISCIPLINE)
# ==============================================================================
MIN_PULLBACK_PCT = float(os.getenv("MIN_PULLBACK_PCT", "0.0005"))
WICK_BUFFER_PCT = float(os.getenv("WICK_BUFFER_PCT", "0.0010"))
MAX_ALLOWED_SL_PCT = STOP_LOSS_MAX_PCT

# Multi-tier Take Profit (с плечом 50x):
# +1.2% ход цены = +60.0% ROI (TP1: фиксация 50% + мгновенный безубыток с запасом на комиссию)
# +2.4% ход цены = +120.0% ROI (TP2: фиксация 25%)
# Остаток 25%: динамический трейлинг-стоп 0.7%
TP1_PCT = float(os.getenv("TP1_PCT", "0.012"))
TP2_PCT = float(os.getenv("TP2_PCT", "0.024"))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.007"))  # 0.7% trailing (точно как в бектесте)
TAKER_FEE_PCT = float(os.getenv("TAKER_FEE_PCT", "0.0005"))         # 0.05% биржевой сбор

# ==============================================================================
# 5. MARKET SCANNER & ELITE HIGH-LIQUIDITY UNIVERSE
# ==============================================================================
MIN_24H_VOLUME_USDT = float(os.getenv("MIN_24H_VOLUME_USDT", "10000000"))  # $10M минимум (отсекает сонные щиткоины с фальшивым стаканом, но пропускает любые ракеты)
SCAN_TICKERS_LIMIT = int(os.getenv("SCAN_TICKERS_LIMIT", "60"))
STRICT_WHITELIST_ONLY = os.getenv("STRICT_WHITELIST_ONLY", "false").lower() == "true"  # false = динамический радар ракет и объема от $10M
CHOP_MIN_VOLUME_SURGE = float(os.getenv("CHOP_MIN_VOLUME_SURGE", "1.30"))
ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.55"))

# Элитный юниверс доказанной ликвидности (топ мажоры, L1/L2, импульсные мемкоины и ракеты):
TOP_CRYPTO_UNIVERSE = [
    "SOLUSDT", "PEPEUSDT", "DOGEUSDT", "NEARUSDT", "SUIUSDT",
    "ENAUSDT", "JUPUSDT", "RENDERUSDT", "WIFUSDT", "APTUSDT",
    "TIAUSDT", "SEIUSDT", "AVAXUSDT", "LINKUSDT", "INJUSDT",
    "FETUSDT", "OPUSDT", "ARBUSDT", "BTCUSDT", "ETHUSDT",
    "BNBUSDT", "XRPUSDT", "SHIBUSDT", "1000PEPEUSDT", "1000SHIBUSDT",
    "BONKUSDT", "1000BONKUSDT", "FLOKIUSDT", "POPCATUSDT", "NEIROUSDT",
    "MOODENGUSDT", "GOATUSDT", "ACTUSDT", "PNUTUSDT", "DRIFTUSDT",
    "GRASSUSDT", "VIRTUALUSDT", "AIXBTUSDT", "PENDLEUSDT", "UNIUSDT",
    "AAVEUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "FILUSDT",
    "TONUSDT", "TAOUSDT", "PYTHUSDT", "JTOUSDT", "RAYUSDT",
    "ORDIUSDT", "BEAMXUSDT", "POWRUSDT", "GTCUSDT"
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

