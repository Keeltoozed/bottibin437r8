import os
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# 1. GROQ AI ENGINE CONFIG (JEV ROCKET HUNTER ENGINE)
# ==============================================================================
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")
GROQ_PRIMARY_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
GROQ_FALLBACK_MODEL = os.getenv("GROQ_MODEL_FALLBACK", "openai/gpt-oss-20b").strip()
GROQ_RPM_LIMIT = int(os.getenv("GROQ_RPM_LIMIT", "25"))  # Безопасный лимит Groq Free Tier (до 30 RPM)
GROQ_MIN_CONFIDENCE = float(os.getenv("GROQ_MIN_CONFIDENCE", "0.65"))  # 65% минимальная уверенность ИИ

# Диапазоны RSI для структурных пробоев (Momentum Ignition):
# На свежем пробое многочасовой базы RSI закономерно выходит в 70-85 (это импульс, а не разворот!)
MIN_RSI_LONG = float(os.getenv("MIN_RSI_LONG", "48.0"))
MAX_RSI_LONG = float(os.getenv("MAX_RSI_LONG", "86.0"))
MIN_RSI_SHORT = float(os.getenv("MIN_RSI_SHORT", "14.0"))
MAX_RSI_SHORT = float(os.getenv("MAX_RSI_SHORT", "52.0"))

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
# 3. TRADING & FIXED-RISK SIZING (STRUCTURAL ROCKET HUNTER)
# ==============================================================================
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "20.0"))

# Фиксированный долларовый риск на сделку (Prop-Desk Risk Sizing):
# 3.5% от эквити (~$0.70 на $20 депозита с плечом 15x) — ощутимо разгоняет суточный профит с ракет!
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.035"))
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "6.0"))  # Базовый ориентир маржи (до 50% свободного кэша)
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_POSITIONS", "2"))   # До 2 параллельных независимых позиций
LEVERAGE = int(os.getenv("LEVERAGE", "15"))                       # 15x эффективное плечо под разгон ракет
ENABLE_SHORT = os.getenv("ENABLE_SHORT", "true").lower() == "true"

# Предохранитель депозита (Circuit Breaker):
# По запросу пользователя заморозка торговли при серии минусов ОТКЛЮЧЕНА (бот торгует непрерывно 24/7):
ENABLE_CIRCUIT_BREAKER = os.getenv("ENABLE_CIRCUIT_BREAKER", "false").lower() == "true"
DAILY_LOSS_LIMIT = int(os.getenv("DAILY_LOSS_LIMIT", "99"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "99"))
CONSECUTIVE_LOSS_PAUSE_SECONDS = int(os.getenv("CONSECUTIVE_LOSS_PAUSE_SECONDS", "0"))  # Без пауз заморозки
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "999.00"))

# ==============================================================================
# 4. STRUCTURAL BREAKOUT FILTERS (MOMENTUM IGNITION — БЕЗ ОШИБКИ НИЖНЕГО ФИТИЛЯ!)
# ==============================================================================
BREAKOUT_LOOKBACK_BARS = int(os.getenv("BREAKOUT_LOOKBACK_BARS", "20"))  # Пробой хая/лоя за 20 закрытых 5m свечей (1ч 40м структуры)
FAST_IGNITION_LOOKBACK_BARS = int(os.getenv("FAST_IGNITION_LOOKBACK_BARS", "12"))  # Быстрый пробой 1ч базы при взрывном объеме >= 2.8x
FAST_IGNITION_SURGE = float(os.getenv("FAST_IGNITION_SURGE", "2.80"))

MIN_5M_VOLUME_SURGE_RATIO = float(os.getenv("MIN_5M_VOLUME_SURGE_RATIO", "1.80"))  # Реальный всплеск RVOL >= 1.80x к 20-свечной средней
MIN_VOLUME_SURGE = MIN_5M_VOLUME_SURGE_RATIO
MIN_5M_PRICE_IMPULSE_PCT = float(os.getenv("MIN_5M_PRICE_IMPULSE_PCT", "0.60"))    # Импульс свечи от 0.60% (и >= 0.9 * ATR14)
MIN_IMPULSE_PCT = MIN_5M_PRICE_IMPULSE_PCT

# Сила закрытия бара (Close Location Value — Marubozu дружелюбно!):
# Для LONG закрытие в верхних 32% диапазона свечи (>= 0.68), для SHORT — в нижних 32%.
MIN_CLOSE_STRENGTH = float(os.getenv("MIN_CLOSE_STRENGTH", "0.68"))
WICK_REJECTION_MIN = 0.0  # УДАЛЕН вредный фильтр нижнего фитиля, резавший 90% истинных Marubozu-ракет!
WICK_EXHAUSTION_MAX = float(os.getenv("WICK_EXHAUSTION_MAX", "0.28"))              # Встречный фитиль истощения <= 28% (отсев Bull/Bear Trap)
MAX_EMA21_EXTENSION_PCT = float(os.getenv("MAX_EMA21_EXTENSION_PCT", "0.035"))     # Защита от погони за улетевшей 5-й свечой (>3.5% от EMA21)
MAX_LIVE_DRIFT_PCT = float(os.getenv("MAX_LIVE_DRIFT_PCT", "0.008"))               # Не догонять цену, если внутри текущей свечи улетела > +0.8%

# Честные структурные границы стоп-лосса (БЕЗ искусственного обрезания внутри свечи!):
STOP_LOSS_MIN_PCT = float(os.getenv("STOP_LOSS_MIN_PCT", "0.005"))  # 0.50% минимальный структурный стоп
STOP_LOSS_MAX_PCT = float(os.getenv("STOP_LOSS_MAX_PCT", "0.022"))  # 2.20% максимальный структурный стоп (шире — сетап пропускается)
MAX_ALLOWED_SL_PCT = STOP_LOSS_MAX_PCT
WICK_BUFFER_PCT = float(os.getenv("WICK_BUFFER_PCT", "0.0010"))     # 0.10% буфер за экстремум фитиля
MIN_PULLBACK_PCT = float(os.getenv("MIN_PULLBACK_PCT", "0.0005"))

# ==============================================================================
# 5. ASYMMETRIC TREND-FOLLOWING EXIT ENGINE (30% / 30% / 40% ATR RUNNER + TIME-STOP)
# ==============================================================================
TARGET_1_R = float(os.getenv("TARGET_1_R", "1.5"))           # TP1 на +1.5R: фиксация 25% + стоп в безубыток (+0.20%)
TARGET_2_R = float(os.getenv("TARGET_2_R", "3.0"))           # TP2 на +3.0R: фиксация еще 25% + защита +1.2R
TP1_PARTIAL_PCT = 0.25                                       # 25% от начальной позиции на TP1
TP2_PARTIAL_OF_REMAINING = round(0.25 / 0.75, 4)             # 33.33% от остатка (25% от начальной), оставляя 50% ранера!

TP1_PCT = float(os.getenv("TP1_PCT", "0.012"))               # Минимальный порог TP1 (1.2% хода цены)
TP2_PCT = float(os.getenv("TP2_PCT", "0.024"))               # Минимальный порог TP2 (2.4% хода цены)

RUNNER_ATR_MULT = float(os.getenv("RUNNER_ATR_MULT", "2.5")) # Chandelier ATR трейлинг 2.5 * ATR14 для ловли ракет +5%..+15%
RUNNER_ACTIVATION_R = float(os.getenv("RUNNER_ACTIVATION_R", "2.2"))  # Включение подтяжки трейла от +2.2R (не душит откат после TP1!)
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.013"))    # Минимальная дистанция трейла 1.3% против рыночного шума
TIME_STOP_MINUTES = int(os.getenv("TIME_STOP_MINUTES", "35"))         # Time-Stop: выход через 35 мин, если импульс затух (< +0.45R без TP1)
STAGNATION_EXIT_MINUTES = int(os.getenv("STAGNATION_EXIT_MINUTES", "18"))  # Быстрый скретч-выход через 18 мин, если монета застряла в мертвом флэте
TAKER_FEE_PCT = float(os.getenv("TAKER_FEE_PCT", "0.0005"))           # 0.05% биржевой сбор тейкера

# ==============================================================================
# 6. MARKET SCANNER & EXPANDED LIQUID BINANCE UNIVERSE (200+ ПАР)
# ==============================================================================
MIN_24H_VOLUME_USDT = max(float(os.getenv("MIN_24H_VOLUME_USDT", "5000000")), 5000000.0)  # $5M на fapi Perpetual
SPOT_MIRROR_MIN_VOL_USDT = float(os.getenv("SPOT_MIRROR_MIN_VOL_USDT", "350000"))         # $350K Spot USDT на vision (охват 200+ реальных пар Binance)
SCAN_TICKERS_LIMIT = min(int(os.getenv("SCAN_TICKERS_LIMIT", "220")), 250)                # Охват до 220-250 крипто-пар Binance
MIN_24H_TRADES_COUNT = int(os.getenv("MIN_24H_TRADES_COUNT", "2500"))                      # Минимум 2500 сделок в сутки (защита от монет-призраков)
MIN_AVG_5M_QUOTE_VOL = float(os.getenv("MIN_AVG_5M_QUOTE_VOL", "2500.0"))                 # Минимум $2500 средний объем 5m свечи (отсев $178 свечей как на HEMI)
MIN_V3_VOLUME_PERSISTENCE = float(os.getenv("MIN_V3_VOLUME_PERSISTENCE", "1.15"))          # Кумулятивный приток объема за 3 свечи (15 мин) >= 1.15x
ENABLE_MTF_15M_FILTER = os.getenv("ENABLE_MTF_15M_FILTER", "true").lower() == "true"       # 15m Multi-Timeframe Guard (защита от лонгов против падающего рынка)
MAX_24H_CHANGE_CAP = float(os.getenv("MAX_24H_CHANGE_CAP", "38.0"))       # Отсев перегретых +40% пампов на стадии раздачи
STRICT_WHITELIST_ONLY = os.getenv("STRICT_WHITELIST_ONLY", "false").lower() == "true"
CHOP_MIN_VOLUME_SURGE = float(os.getenv("CHOP_MIN_VOLUME_SURGE", "1.50"))
ML_MIN_FILTER_PROB = float(os.getenv("ML_MIN_FILTER_PROB", "0.42"))       # Валидированный порог отсева слабых сетапов по закрытой свече
ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.52"))

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
    "ORDIUSDT", "BEAMXUSDT", "POWRUSDT", "GTCUSDT", "WLDUSDT", "ONDOUSDT"
]

# Корни токенизированных акций и ETF (отсекают как <ROOT>USDT, так и <ROOT>BUSDT на Spot/Vision):
STOCK_TICKER_ROOTS = {
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOG", "GOOGL", "META", "MSTR",
    "COIN", "QQQ", "SPY", "SOXL", "SOXS", "INTC", "INTW", "SNDK", "CRCL",
    "SPCX", "SKHY", "SKHYNIX", "KORU", "AMD", "PLTR", "HOOD", "NFLX", "BABA",
    "MU", "BNC", "AKE"
}

# Черный список: стейблкоины, фиат, золото/металлы, хаки и синтетические акции
EXCLUDED_TICKERS = {
    # Стейблкоины, синтетический доллар, фиат и золото
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "EURUSDT", "EURIUSDT", "AEURUSDT",
    "DAIUSDT", "USTCUSDT", "USD1USDT", "USDEUSDT", "RLUSDUSDT", "RWUSDUSDT", "UUSDT",
    "BFUSDUSDT", "PAXGUSDT", "XAUUSDT", "XAUTUSDT", "XAGUSDT",
    # Традиционные акции и ETF
    "GOOGLUSDT", "MSTRUSDT", "QQQUSDT", "MUUSDT", "SOXSUSDT", "SPYUSDT", "NVDAUSDT",
    "TSLAUSDT", "AAPLUSDT", "AMZNUSDT", "MSFTUSDT", "COINBUSDT", "SOXLUSDT", "INTCUSDT", "SNDKUSDT",
    "SKHYNIXUSDT", "SKHYUSDT", "KORUUSDT", "SPCXUSDT", "AKEUSDT", "CRCLUSDT",
    # Хакнутые/делистнутые/проблемные токены
    "INITUSDT", "CRVUSDT", "MEGAUSDT", "AVAUSDT", "SOLVUSDT", "BIRBUSDT",
    "COCOSUSDT", "RNDRUSDT", "GALUSDT", "POLYUSDT"
}
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.0022"))  # 0.22% max spread (учитывает тик-шаг на Spot/Vision зеркале)
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "12"))
PAIR_COOLDOWN_MINUTES = int(os.getenv("PAIR_COOLDOWN_MINUTES", "5"))

# ==============================================================================
# 7. TELEGRAM NOTIFICATIONS (FAIL-SAFE OPTIONAL)
# ==============================================================================
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
ENABLE_TELEGRAM = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# ==============================================================================
# 8. SERVER / RENDER SETTINGS
# ==============================================================================
PORT = int(os.getenv("PORT", "8501"))
RENDER = bool(os.getenv("RENDER"))
