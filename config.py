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
# 2.5% от эквити ($0.50 на $20 депозита с учетом комиссий) — любой стоп контролируем,
# а пойманная ракета 3R-6R приносит +$1.20..+$2.50+!
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.025"))
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "4.5"))  # Базовый ориентир маржи (ограничен 45% свободного кэша)
MAX_CONCURRENT_POSITIONS = min(int(os.getenv("MAX_POSITIONS", "2")), 2)  # Строго не более 2 позиций одновременно для $20 депозита
LEVERAGE = int(os.getenv("LEVERAGE", "12"))                       # 12x оптимальное плечо под риск-сайзинг
ENABLE_SHORT = os.getenv("ENABLE_SHORT", "true").lower() == "true"

# Институциональный предохранитель депозита (Circuit Breaker):
DAILY_LOSS_LIMIT = int(os.getenv("DAILY_LOSS_LIMIT", "3"))
ENABLE_CIRCUIT_BREAKER = True
MAX_CONSECUTIVE_LOSSES = 2
CONSECUTIVE_LOSS_PAUSE_SECONDS = 2700  # 45 минут охлаждения после 2 полных стопов подряд
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "2.00"))

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
TARGET_1_R = float(os.getenv("TARGET_1_R", "1.5"))           # TP1 на +1.5R: фиксация 30% + стоп в безубыток (+0.20%)
TARGET_2_R = float(os.getenv("TARGET_2_R", "3.0"))           # TP2 на +3.0R: фиксация еще 30% + защита +1.2R
TP1_PARTIAL_PCT = 0.30                                       # 30% от начальной позиции на TP1
TP2_PARTIAL_OF_REMAINING = round(0.30 / 0.70, 4)             # 42.86% от остатка (30% от начальной), оставляя 40% ранера!

TP1_PCT = float(os.getenv("TP1_PCT", "0.012"))               # Минимальный порог TP1 (1.2% хода цены)
TP2_PCT = float(os.getenv("TP2_PCT", "0.024"))               # Минимальный порог TP2 (2.4% хода цены)

RUNNER_ATR_MULT = float(os.getenv("RUNNER_ATR_MULT", "2.5")) # Chandelier ATR трейлинг 2.5 * ATR14 для ловли ракет +5%..+15%
RUNNER_ACTIVATION_R = float(os.getenv("RUNNER_ACTIVATION_R", "2.2"))  # Включение подтяжки трейла от +2.2R (не душит откат после TP1!)
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.013"))    # Минимальная дистанция трейла 1.3% против рыночного шума
TIME_STOP_MINUTES = int(os.getenv("TIME_STOP_MINUTES", "35"))         # Time-Stop: выход через 35 мин, если импульс затух (< +0.45R без TP1)
TAKER_FEE_PCT = float(os.getenv("TAKER_FEE_PCT", "0.0005"))           # 0.05% биржевой сбор тейкера

# ==============================================================================
# 6. MARKET SCANNER & LIQUID ROCKET UNIVERSE
# ==============================================================================
MIN_24H_VOLUME_USDT = max(float(os.getenv("MIN_24H_VOLUME_USDT", "8000000")), 8000000.0)  # Строгий пол $8M (защита от тонких щиткоинов из старых env)
SCAN_TICKERS_LIMIT = min(int(os.getenv("SCAN_TICKERS_LIMIT", "110")), 120)                # Оптимальный радар до 120 пар без риска бана 429
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
