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
GROQ_MIN_CONFIDENCE = float(os.getenv("GROQ_MIN_CONFIDENCE", "0.68"))  # Повышен порог для отсева мусора (только A+ сетапы)

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
COMPOUND_RISK_PCT = float(os.getenv("COMPOUND_RISK_PCT", "0.10"))  # 10% от депозита на сделку ($2 при $20, $2.70 при $27)
MAX_RISK_PER_TRADE_USD = float(os.getenv("MAX_RISK_PER_TRADE_USD", "1.00")) # минимум $1.00
ENABLE_CIRCUIT_BREAKER = os.getenv("ENABLE_CIRCUIT_BREAKER", "false").lower() == "true"  # Отключен стоп по торговле
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "999999.00"))  # Без дневной остановки бота
TARGET_1_R = 2.0  # Цель 1: 2R
TARGET_2_R = 3.5  # Цель 2: 3.5R
ENABLE_SHORT = os.getenv("ENABLE_SHORT", "true").lower() == "true"  # Торговля в LONG и SHORT

# Для капитала $20: $6 маржа на сделку (2 сделки = $12 в работе, $8 свободный резерв)
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "6.0"))
LEVERAGE = 60  # Значение по умолчанию: 60x (Оптимальный баланс высокой прибыли и сниженной просадки)
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_POSITIONS", "2"))

# ==============================================================================
# 4. EXIT STRATEGY & "THE LINE" (GROK x JEV RULES DEDICATED FOR 60x LEVERAGE)
# ==============================================================================
# "We bid the flush, not the candle": pullback required before entry
MIN_PULLBACK_PCT = float(os.getenv("MIN_PULLBACK_PCT", "0.0005"))  # 0.05% pullback

# "The stop lives under the wick": жесткий снайперский стоп для 60x плеча (не более 0.75%)
# Запрещает сделки с широкими размашистыми фитилями вроде STX (где стоп был 1.2% и привел к убытку 84%)
WICK_BUFFER_PCT = float(os.getenv("WICK_BUFFER_PCT", "0.0008"))
MAX_ALLOWED_SL_PCT = float(os.getenv("MAX_ALLOWED_SL_PCT", "0.0075"))  # Макс. 0.75% SL (строгое ограничение убытка на 60x)

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
# 5. MARKET SCANNER & BROAD CRYPTO UNIVERSE (TOP 130+ ACTIVE COINS)
# ==============================================================================
# Снижен минимальный суточный объем с $50M до $8M, чтобы ловить взрывные импульсы на 130+ монетах!
MIN_24H_VOLUME_USDT = float(os.getenv("MIN_24H_VOLUME_USDT", "8000000"))  # $8M
SCAN_TICKERS_LIMIT = int(os.getenv("SCAN_TICKERS_LIMIT", "130"))  # Сканируем 130 самых активных пар Binance
STRICT_WHITELIST_ONLY = os.getenv("STRICT_WHITELIST_ONLY", "false").lower() == "true"  # Динамический отбор всех ликвидных пар
ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.68"))  # 68% уверенность модели для входа

# Элитный юниверс криптовалют (160+ проверенных монет)
TOP_CRYPTO_UNIVERSE = [
    # Топ-10 Мажоры и L1 гиганты
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "AVAXUSDT", "SUIUSDT",
    # Топ L1/L2 и инфраструктурные лидеры
    "NEARUSDT", "LINKUSDT", "APTUSDT", "RENDERUSDT", "TIAUSDT", "SEIUSDT", "ENAUSDT", "JUPUSDT", "INJUSDT", "AAVEUSDT",
    "DOTUSDT", "LTCUSDT", "BCHUSDT", "OPUSDT", "ARBUSDT", "FILUSDT", "STXUSDT", "ONDOUSDT", "WLDUSDT", "TAOUSDT", "TONUSDT",
    "ATOMUSDT", "XLMUSDT", "ETCUSDT", "KASUSDT", "ALGOUSDT", "THETAUSDT", "KAVAUSDT", "ZECUSDT", "XMRUSDT", "FTMUSDT", "EGLDUSDT",
    # Высоколиквидные мемкоины и импульсные активы
    "PEPEUSDT", "1000PEPEUSDT", "WIFUSDT", "SHIBUSDT", "1000SHIBUSDT", "BONKUSDT", "1000BONKUSDT", "FLOKIUSDT", "1000FLOKIUSDT",
    "BOMEUSDT", "MEMEUSDT", "TURBOUSDT", "1000SATSUSDT", "NEIROUSDT", "PENGUUSDT", "POPCATUSDT", "MEWUSDT", "BRETTUSDT",
    "MOODENGUSDT", "GOATUSDT", "ACTUSDT", "PNUTUSDT", "COWUSDT", "CETUSUSDT", "GRASSUSDT", "DRIFTUSDT", "VIRTUALUSDT", "AIXBTUSDT",
    "DOGSUSDT", "NOTUSDT", "HMSTRUSDT", "CATIUSDT", "SLERFUSDT",
    # Топ DeFi, AI и Web3
    "FETUSDT", "UNIUSDT", "PENDLEUSDT", "ZROUSDT", "STRKUSDT", "PYTHUSDT", "JTOUSDT", "BLURUSDT",
    "GALAUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT", "CHZUSDT", "DYDXUSDT", "GMXUSDT", "LDOUSDT", "RAYUSDT", "ORDIUSDT",
    "BEAMXUSDT", "HYPEUSDT", "QNTUSDT", "AINUSDT", "LSKUSDT", "QUSDT", "SOPHUSDT", "INTWUSDT", "BTWUSDT", "PUMPUSDT",
    "BLESSUSDT", "AIOTUSDT", "MAGMAUSDT", "PARTIUSDT", "ETHFIUSDT", "REZUSDT", "BBUSDT", "IOUSDT", "ZKUSDT", "LISTAUSDT",
    "WUSDT", "OMUSDT", "KAIAUSDT", "SAGAUSDT", "TNSRUSDT", "SAFEUSDT", "KMNOUSDT", "TRUUSDT", "LQTYUSDT", "SPELLUSDT",
    "GASUSDT", "ARKUSDT", "LOOMUSDT", "HIFIUSDT", "POLUSDT", "BIGTIMEUSDT", "SUPERUSDT", "ARKMUSDT", "AIUSDT", "NFPUSDT",
    "GLMUSDT", "ATHUSDT", "ARUSDT", "HNTUSDT", "MOBILEUSDT", "IOTXUSDT", "AIOZUSDT", "RONINUSDT", "METISUSDT", "MANTAUSDT", "SCRUSDT"
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

