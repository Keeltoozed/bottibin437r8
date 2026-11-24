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
# 3.0% от эквити (~$0.60 на $20 депозита с плечом 15x) + 1.35x буст на A+ ракетах (ML >= 58%, RVOL >= 1.9x)!
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.030"))
CONVICTION_RISK_MULT = float(os.getenv("CONVICTION_RISK_MULT", "1.35"))
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "4.0"))  # Базовый ориентир маржи (ограничен 45% свободного кэша)
MAX_CONCURRENT_POSITIONS = min(int(os.getenv("MAX_POSITIONS", "2")), 3)   # До 2-3 позиций одновременно для $20 депозита
LEVERAGE = int(os.getenv("LEVERAGE", "15"))                       # 15x оптимальное плечо под риск-сайзинг
ENABLE_SHORT = os.getenv("ENABLE_SHORT", "true").lower() == "true"

# Предохранитель депозита (Circuit Breaker):
# По запросу пользователя заморозка торговли при серии минусов ОТКЛЮЧЕНА (бот торгует непрерывно 24/7):
ENABLE_CIRCUIT_BREAKER = os.getenv("ENABLE_CIRCUIT_BREAKER", "false").lower() == "true"
DAILY_LOSS_LIMIT = int(os.getenv("DAILY_LOSS_LIMIT", "99"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "99"))
CONSECUTIVE_LOSS_PAUSE_SECONDS = int(os.getenv("CONSECUTIVE_LOSS_PAUSE_SECONDS", "0"))  # Без пауз заморозки
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "999.00"))

# ==============================================================================
# 4. STRUCTURAL BREAKOUT & CONTINUATION FILTERS (3-STAGE ROCKET CATCHER)
# ==============================================================================
BREAKOUT_LOOKBACK_BARS = int(os.getenv("BREAKOUT_LOOKBACK_BARS", "12"))  # Пробой хая/лоя за 12 закрытых 5m свечей (1ч структуры)
FAST_IGNITION_LOOKBACK_BARS = int(os.getenv("FAST_IGNITION_LOOKBACK_BARS", "8"))   # Быстрый пробой 40м базы при взрывном объеме >= 2.4x
FAST_IGNITION_SURGE = float(os.getenv("FAST_IGNITION_SURGE", "2.40"))
CONTINUATION_LOOKBACK_BARS = int(os.getenv("CONTINUATION_LOOKBACK_BARS", "5"))     # 5-барный Bull/Bear Flag пробой продолжения тренда
ENABLE_FLAG_CONTINUATION = os.getenv("ENABLE_FLAG_CONTINUATION", "true").lower() == "true"
ENABLE_LIVE_INTRABAR_IGNITION = os.getenv("ENABLE_LIVE_INTRABAR_IGNITION", "true").lower() == "true"

MIN_5M_VOLUME_SURGE_RATIO = float(os.getenv("MIN_5M_VOLUME_SURGE_RATIO", "1.45"))  # Валидированный RVOL >= 1.45x к 20-свечной средней
MIN_VOLUME_SURGE = MIN_5M_VOLUME_SURGE_RATIO
MIN_5M_PRICE_IMPULSE_PCT = float(os.getenv("MIN_5M_PRICE_IMPULSE_PCT", "0.42"))    # Импульс свечи от 0.42% (и >= 0.90 * ATR14)
MIN_IMPULSE_PCT = MIN_5M_PRICE_IMPULSE_PCT
MIN_ATR_PCT = float(os.getenv("MIN_ATR_PCT", "0.0025"))                           # Минимум 0.25% 5m ATR (отсев мертвого штиля)

# Сила закрытия бара (Close Location Value — Marubozu дружелюбно!):
# Для LONG закрытие в верхних 32% диапазона свечи (>= 0.68), для SHORT — в нижних 32%.
MIN_CLOSE_STRENGTH = float(os.getenv("MIN_CLOSE_STRENGTH", "0.68"))
WICK_REJECTION_MIN = float(os.getenv("WICK_REJECTION_MIN", "0.0"))
WICK_EXHAUSTION_MAX = float(os.getenv("WICK_EXHAUSTION_MAX", "0.28"))              # Встречный фитиль истощения <= 28% (отсев Bull/Bear Trap)
MAX_EMA21_EXTENSION_PCT = float(os.getenv("MAX_EMA21_EXTENSION_PCT", "0.035"))     # Защита от погони за улетевшей 5-й свечой (>3.5% от EMA21)
MAX_LIVE_DRIFT_PCT = float(os.getenv("MAX_LIVE_DRIFT_PCT", "0.016"))

# Честные структурные границы стоп-лосса и нормализация маржи (анти-перекос на тихих монетах):
STOP_LOSS_MIN_PCT = float(os.getenv("STOP_LOSS_MIN_PCT", "0.0055"))  # 0.55% минимальный структурный стоп
STOP_LOSS_MAX_PCT = float(os.getenv("STOP_LOSS_MAX_PCT", "0.0135"))  # 1.35% максимальный структурный стоп (защита от -27% просадок)
MAX_ALLOWED_SL_PCT = STOP_LOSS_MAX_PCT
SIZING_SL_FLOOR_PCT = float(os.getenv("SIZING_SL_FLOOR_PCT", "0.0085"))  # Пол знаменателя сайзинга 0.85%
MIN_MARGIN_EQUITY_PCT = float(os.getenv("MIN_MARGIN_EQUITY_PCT", "0.15"))  # Минимум ~15% эквити ($3.00) на ракету
MAX_MARGIN_EQUITY_PCT = float(os.getenv("MAX_MARGIN_EQUITY_PCT", "0.22"))  # Максимум ~22% эквити ($4.40) на 1 сделку
WICK_BUFFER_PCT = float(os.getenv("WICK_BUFFER_PCT", "0.0010"))     # 0.10% буфер за экстремум фитиля
MIN_PULLBACK_PCT = float(os.getenv("MIN_PULLBACK_PCT", "0.0005"))

# ==============================================================================
# 5. PROFIT-SHIELD EXIT ENGINE (45% / 30% / 25% + EARLY BE + 35M TIME-STOP)
# ==============================================================================
EARLY_BE_TRIGGER_PCT = float(os.getenv("EARLY_BE_TRIGGER_PCT", "0.0070"))  # +0.70% хода цены (+10.5% ROI 15x) -> стоп в безубыток +0.22%
EARLY_BE_TRIGGER_R = float(os.getenv("EARLY_BE_TRIGGER_R", "0.85"))
EARLY_BE_LOCK_PCT = float(os.getenv("EARLY_BE_LOCK_PCT", "0.0022"))        # Безубыток +0.22% (покрывает комиссии 0.12% и дает твердый +)

TARGET_1_R = float(os.getenv("TARGET_1_R", "1.40"))          # Доступный TP1 на +1.40R (min +0.95% цены): фиксация 45% в кэш
TARGET_2_R = float(os.getenv("TARGET_2_R", "2.70"))          # TP2 на +2.70R (min +2.00% цены): фиксация еще 30% + защита +1.20R
TP1_PARTIAL_PCT = 0.45                                       # 45% от начальной позиции на TP1 (немедленный кэш в карман!)
TP2_PARTIAL_OF_REMAINING = round(0.30 / 0.55, 4)             # 54.55% от остатка (30% от начальной), оставляя 25% Moonbag ранера!

TP1_PCT = float(os.getenv("TP1_PCT", "0.0095"))              # Минимальный порог TP1 (0.95% хода цены)
TP2_PCT = float(os.getenv("TP2_PCT", "0.0200"))              # Минимальный порог TP2 (2.00% хода цены)

RUNNER_ATR_MULT = float(os.getenv("RUNNER_ATR_MULT", "2.4"))               # Chandelier ATR трейлинг 2.4 * ATR14
RUNNER_ACTIVATION_R = float(os.getenv("RUNNER_ACTIVATION_R", "2.1"))       # Включение трейла от +2.1R (не душит ракеты!)
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.0115"))        # Минимальная дистанция трейла 1.15%
TIME_STOP_MINUTES = int(os.getenv("TIME_STOP_MINUTES", "35"))              # Time-Stop 35 мин (освобождает слоты от затухших сделок)
STAGNATION_EXIT_MINUTES = int(os.getenv("STAGNATION_EXIT_MINUTES", "20"))
TAKER_FEE_PCT = float(os.getenv("TAKER_FEE_PCT", "0.0005"))                # 0.05% биржевой сбор тейкера

# ==============================================================================
# 6. MARKET SCANNER & EXPANDED LIQUID BINANCE UNIVERSE (200+ ЧИСТЫХ КРИПТО-ПАР)
# ==============================================================================
MIN_24H_VOLUME_USDT = max(float(os.getenv("MIN_24H_VOLUME_USDT", "20000000")), 15000000.0)  # $15M-$20M глубина ликвидности на fapi
SPOT_MIRROR_MIN_VOL_USDT = float(os.getenv("SPOT_MIRROR_MIN_VOL_USDT", "1500000"))         # $1.5M Spot USDT на vision
SCAN_TICKERS_LIMIT = min(int(os.getenv("SCAN_TICKERS_LIMIT", "200")), 250)                # Охват до 200 ликвидных крипто-пар Binance
MIN_24H_TRADES_COUNT = int(os.getenv("MIN_24H_TRADES_COUNT", "3500"))                      # Минимум 3500 сделок в сутки (защита от монет-призраков)
MIN_AVG_5M_QUOTE_VOL = float(os.getenv("MIN_AVG_5M_QUOTE_VOL", "25000.0"))                 # Минимум $25,000 средний объем 5m свечи
MIN_V3_VOLUME_PERSISTENCE = float(os.getenv("MIN_V3_VOLUME_PERSISTENCE", "1.10"))          # Кумулятивный приток объема за 3 свечи
ENABLE_MTF_15M_FILTER = os.getenv("ENABLE_MTF_15M_FILTER", "true").lower() == "true"       # 15m Multi-Timeframe Guard
MAX_24H_CHANGE_CAP = float(os.getenv("MAX_24H_CHANGE_CAP", "100.0"))       # Позволяем честно торговать сильнейшими импульсными ракетами (до +100% за сутки)
STRICT_WHITELIST_ONLY = os.getenv("STRICT_WHITELIST_ONLY", "true").lower() == "true"
CHOP_MIN_VOLUME_SURGE = float(os.getenv("CHOP_MIN_VOLUME_SURGE", "1.45"))
ML_MIN_FILTER_PROB = float(os.getenv("ML_MIN_FILTER_PROB", "0.55"))       # Валидированный институциональный порог ML (>= 55%, PF 1.96)
ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.55"))

def round_price(val: float) -> float:
    """Форматирует цену с сохранением 8 значащих цифр (защита мемов и дешевых монет от обрезки round(x, 6))."""
    if val is None or val <= 0:
        return 0.0
    if val >= 1.0:
        return round(val, 6)
    return float(f"{val:.8g}")

# Элитный юниверс доказанной ликвидности (топ мажоры, L1/L2, импульсные мемкоины и ракеты):
TOP_CRYPTO_UNIVERSE = [
    "SOLUSDT", "1000PEPEUSDT", "DOGEUSDT", "NEARUSDT", "SUIUSDT",
    "ENAUSDT", "JUPUSDT", "RENDERUSDT", "WIFUSDT", "APTUSDT",
    "TIAUSDT", "SEIUSDT", "AVAXUSDT", "LINKUSDT", "INJUSDT",
    "FETUSDT", "OPUSDT", "ARBUSDT", "BTCUSDT", "ETHUSDT",
    "BNBUSDT", "XRPUSDT", "1000SHIBUSDT", "1000BONKUSDT", "1000FLOKIUSDT",
    "POPCATUSDT", "NEIROUSDT", "MOODENGUSDT", "GOATUSDT", "ACTUSDT",
    "PNUTUSDT", "DRIFTUSDT", "GRASSUSDT", "VIRTUALUSDT", "AIXBTUSDT",
    "PENDLEUSDT", "UNIUSDT", "AAVEUSDT", "DOTUSDT", "LTCUSDT",
    "BCHUSDT", "FILUSDT", "TONUSDT", "TAOUSDT", "PYTHUSDT",
    "JTOUSDT", "RAYUSDT", "ORDIUSDT", "BEAMXUSDT", "POWRUSDT",
    "GTCUSDT", "WLDUSDT", "ONDOUSDT", "PEPEUSDT", "SHIBUSDT", "BONKUSDT", "FLOKIUSDT",
    "STXUSDT", "CRVUSDT", "DYDXUSDT", "FTMUSDT", "ENSUSDT", "GALAUSDT", "KASUSDT"
]

# Полный список 255 не-криптовалютных контрактов TradFi (акции США/Гонконга/Кореи/Китая, ETF, сырье, индексы):
TRADFI_EXCLUSION_SET = {
    "AAOIUSDT", "AAPLUSDT", "ABBVUSDT", "ACNUSDT", "ADBEUSDT", "AGPUUSDT", "AKAMUSDT", "ALABUSDT",
    "ALLUSDT", "AMATUSDT", "AMCUSDT", "AMDLUSDT", "AMDUSDT", "AMGNUSDT", "AMZNUSDT", "ANETUSDT",
    "ANTHROPICUSDT", "ANTUSDT", "APLDUSDT", "APPUSDT", "ARMUSDT", "ARTYUSDT", "ASMLUSDT", "ASTSUSDT",
    "AVGOUSDT", "AXTIUSDT", "BABAUSDT", "BACUSDT", "BBXUSDT", "BEUSDT", "BITOUSDT", "BMNRUSDT",
    "BNCUSDT", "BOTUSDT", "BRKBUSDT", "BSPUSDT", "BTCDOMUSDT", "BTCUSDT_261225", "BTCUSDT_270326",
    "BWETUSDT", "BXUSDT", "BYDUSDT", "BZUSDT", "CATUSDT", "CBRSUSDT", "CCJUSDT", "CEGUSDT",
    "CIENUSDT", "CLUSDT", "COHRUSDT", "COINUSDT", "COPPERUSDT", "COSTUSDT", "CRCLUSDT", "CRDOUSDT",
    "CRMLUSDT", "CRMUSDT", "CRWDUSDT", "CRWVUSDT", "CSCOUSDT", "CSOPSAMSUNG2LUSDT", "CSOPSKHYNIX2LUSDT",
    "CVNAUSDT", "CXMTUSDT", "CYPHUSDT", "DDOGUSDT", "DEFIUSDT", "DELLUSDT", "DISUSDT", "DJTUSDT",
    "DKNGUSDT", "DRAMUSDT", "EBAYUSDT", "EIDOUSDT", "EQTUSDT", "ETHUSDT_261225", "ETHUSDT_270326",
    "ETNUSDT", "EWJUSDT", "EWTUSDT", "EWYUSDT", "EWZSUSDT", "EWZUSDT", "FLEXUSDT", "FLNCUSDT",
    "FRHCUSDT", "FWDIUSDT", "GDXUSDT", "GEVUSDT", "GIGADEVUSDT", "GLWUSDT", "GMEUSDT", "GOOGLUSDT",
    "GPROUSDT", "GSUSDT", "GTLBUSDT", "HANMIUSDT", "HDUSDT", "HIMSUSDT", "HK0625USDT", "HK0700USDT",
    "HK0992USDT", "HK1810USDT", "HOODUSDT", "HPEUSDT", "HUTUSDT", "HYUNDAIUSDT", "IBITUSDT",
    "IBKRUSDT", "IBMUSDT", "IGVUSDT", "INTCUSDT", "INTWUSDT", "IONQUSDT", "IRENUSDT", "IWMUSDT",
    "JNJUSDT", "JPMUSDT", "KLACUSDT", "KODEX200USDT", "KORUUSDT", "KOUSDT", "KSTRUSDT", "KUAISHOUUSDT",
    "LGELECTRONICSUSDT", "LITEUSDT", "LLYUSDT", "LRCXUSDT", "LYTEUSDT", "MARAUSDT", "MCDUSDT",
    "MDBUSDT", "MDTUSDT", "MEITUANUSDT", "MELIUSDT", "METAUSDT", "MINIMAXUSDT", "MOONSHOTUSDT",
    "MPUSDT", "MRKUSDT", "MRNAUSDT", "MRVLUSDT", "MSFTUSDT", "MSTRUSDT", "MSTUUSDT", "MUUSDT",
    "MUUUSDT", "MVLLUSDT", "NATGASUSDT", "NAVERUSDT", "NBISUSDT", "NETUSDT", "NFLXUSDT", "NIOUSDT",
    "NKEUSDT", "NOKUSDT", "NOWUSDT", "NUUSDT", "NVDAUSDT", "NVDLUSDT", "NVOUSDT", "OKLOUSDT",
    "ONDSUSDT", "OPENAIUSDT", "ORCLUSDT", "OURAUSDT", "OXYUSDT", "PANWUSDT", "PATHUSDT", "PAYPUSDT",
    "PDDUSDT", "PENGUSDT", "PFEUSDT", "PLTRUSDT", "POPMARTUSDT", "PREDICTUSDT", "PYPLUSDT", "QCOMUSDT",
    "QNTXUSDT", "QQQUSDT", "RAMUSDT", "RDDTUSDT", "RDWUSDT", "RIVNUSDT", "RKLBUSDT", "RUMUSDT",
    "SAMSUNGEMUSDT", "SAMSUNGUSDT", "SECZUSDT", "SHAZUSDT", "SHOPUSDT", "SKDDUSDT", "SKHYNIXUSDT",
    "SKHYUSDT", "SKUUUSDT", "SMCIUSDT", "SMHUSDT", "SMRUSDT", "SNDKUSDT", "SNOWUSDT", "SNPSUSDT",
    "SNXXUSDT", "SOFIUSDT", "SONYUSDT", "SOXLUSDT", "SOXSUSDT", "SOXXUSDT", "SPCXUSD1", "SPCXUSDT",
    "SPYUSDT", "SQQQUSDT", "STMUSDT", "STRCUSDT", "STXXUSDT", "TBTUSDT", "TEAMUSDT", "TEMUSDT",
    "TENCENTUSDT", "TERUSDT", "TMFUSDT", "TQQQUSDT", "TSLAUSDT", "TSLLUSDT", "TSMUSDT", "TTWOUSDT",
    "TWSTUSDT", "TXNUSDT", "TZAUSDT", "UBERUSDT", "UNHUSDT", "UNITREEUSDT", "URNMUSDT", "USARUSDT",
    "USDBRLUSDT", "USDEXUSDT", "UVXYUSDT", "VKTXUSDT", "VRTUSDT", "VSTUSDT", "VUSDT", "WDCUSDT",
    "WENUSDT", "WMTUSDT", "XAGUSDT", "XAUUSDT", "XBIUSDT", "XLEUSDT", "XOMUSDT", "XPDUSDT",
    "XPTUSDT", "ZCSHUSDT", "ZHIPUUSDT", "ZHONGJIUSDT", "ZMUSDT", "ZSUSDT"
}

# Корни токенизированных акций и ETF (отсекают как <ROOT>USDT, так и <ROOT>BUSDT на Spot/Vision):
STOCK_TICKER_ROOTS = {s[:-4] for s in TRADFI_EXCLUSION_SET if s.endswith("USDT")} | {
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOG", "GOOGL", "META", "MSTR",
    "COIN", "QQQ", "SPY", "SOXL", "SOXS", "INTC", "INTW", "SNDK", "CRCL",
    "SPCX", "SKHY", "SKHYNIX", "KORU", "AMD", "PLTR", "HOOD", "NFLX", "BABA",
    "MU", "BNC", "AKE", "TQQQ", "SQQQ", "LRCX", "QCOM", "ASML", "SMH", "AVGO", "PANW", "UNITREE"
}

# Черный список: стейблкоины, фиат, золото/металлы, хаки и все 255 синтетических акций/TradFi
EXCLUDED_TICKERS = TRADFI_EXCLUSION_SET | {
    # Стейблкоины, синтетический доллар, фиат и золото
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "EURUSDT", "EURIUSDT", "AEURUSDT",
    "DAIUSDT", "USTCUSDT", "USD1USDT", "USDEUSDT", "RLUSDUSDT", "RWUSDUSDT", "UUSDT",
    "BFUSDUSDT", "PAXGUSDT", "XAUUSDT", "XAUTUSDT", "XAGUSDT",
    "COINBUSDT", "AKEUSDT",
    # Хакнутые/делистнутые/проблемные токены
    "INITUSDT", "CRVUSDT", "MEGAUSDT", "AVAUSDT", "SOLVUSDT", "BIRBUSDT",
    "COCOSUSDT", "RNDRUSDT", "GALUSDT", "POLYUSDT"
}
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.0022"))  # 0.22% max spread (учитывает тик-шаг на Spot/Vision зеркале)
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "12"))
PAIR_COOLDOWN_MINUTES = int(os.getenv("PAIR_COOLDOWN_MINUTES", "25"))

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
