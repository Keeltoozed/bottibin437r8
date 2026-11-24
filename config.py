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

# Фиксированный долларовый риск на сделку (Геометрический Compounding + Half-Kelly DD Guard):
# 3.0% от текущего эквити (~$0.60 на $20, $1.50 на $50, $3.00 на $100) с автоматическим снижением до 1.8% при просадке > 15%.
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.030"))
CONVICTION_RISK_MULT = float(os.getenv("CONVICTION_RISK_MULT", "1.00"))
DD_GUARD_THRESHOLD = float(os.getenv("DD_GUARD_THRESHOLD", "0.15"))
DD_GUARD_RISK_MULT = float(os.getenv("DD_GUARD_RISK_MULT", "0.60"))
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "4.0"))
MAX_CONCURRENT_POSITIONS = min(int(os.getenv("MAX_POSITIONS", "2")), 3)
LEVERAGE = int(os.getenv("LEVERAGE", "15"))
ENABLE_SHORT = os.getenv("ENABLE_SHORT", "true").lower() == "true"

# Предохранитель депозита (Circuit Breaker):
# По запросу пользователя заморозка торговли при серии минусов ОТКЛЮЧЕНА (бот торгует непрерывно 24/7):
ENABLE_CIRCUIT_BREAKER = os.getenv("ENABLE_CIRCUIT_BREAKER", "false").lower() == "true"
DAILY_LOSS_LIMIT = int(os.getenv("DAILY_LOSS_LIMIT", "99"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "99"))
CONSECUTIVE_LOSS_PAUSE_SECONDS = int(os.getenv("CONSECUTIVE_LOSS_PAUSE_SECONDS", "0"))  # Без пауз заморозки
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "999.00"))

# ==============================================================================
# 4. 6H STRUCTURAL + 3H SQUEEZE + ANTI-RUG ROCKET ENGINE (7/7 SPLITS VALIDATED)
# ==============================================================================
BREAKOUT_LOOKBACK_BARS = int(os.getenv("BREAKOUT_LOOKBACK_BARS", "72"))   # Пробой 6-часовой структуры (72 x 5m свечей)
SQUEEZE_LOOKBACK_BARS = int(os.getenv("SQUEEZE_LOOKBACK_BARS", "36"))     # Ранний старт ракеты из узкого 3ч сжатия (<= 6.5%)
SQUEEZE_MAX_RANGE_PCT = float(os.getenv("SQUEEZE_MAX_RANGE_PCT", "0.065"))
SQUEEZE_MIN_RVOL = float(os.getenv("SQUEEZE_MIN_RVOL", "2.20"))
ENABLE_RUG_HUNTER_SHORT = os.getenv("ENABLE_RUG_HUNTER_SHORT", "true").lower() == "true"  # Перехват сливов после пампа >= +16%
RUG_PUMP_MIN_PCT = float(os.getenv("RUG_PUMP_MIN_PCT", "0.16"))
RUG_SUPPORT_BARS = int(os.getenv("RUG_SUPPORT_BARS", "16"))

FAST_IGNITION_LOOKBACK_BARS = int(os.getenv("FAST_IGNITION_LOOKBACK_BARS", "72"))
FAST_IGNITION_SURGE = float(os.getenv("FAST_IGNITION_SURGE", "99.0"))
CONTINUATION_LOOKBACK_BARS = int(os.getenv("CONTINUATION_LOOKBACK_BARS", "72"))
ENABLE_FLAG_CONTINUATION = os.getenv("ENABLE_FLAG_CONTINUATION", "false").lower() == "true"
ENABLE_LIVE_INTRABAR_IGNITION = os.getenv("ENABLE_LIVE_INTRABAR_IGNITION", "false").lower() == "true"

MIN_5M_VOLUME_SURGE_RATIO = float(os.getenv("MIN_5M_VOLUME_SURGE_RATIO", "2.00"))  # Взрывной RVOL >= 2.00x к 20-свечной средней
MIN_VOLUME_SURGE = MIN_5M_VOLUME_SURGE_RATIO
MIN_5M_PRICE_IMPULSE_PCT = float(os.getenv("MIN_5M_PRICE_IMPULSE_PCT", "0.60"))    # Чистый импульс >= 0.60% (и >= 0.90 * ATR14)
MIN_IMPULSE_PCT = MIN_5M_PRICE_IMPULSE_PCT
MIN_ATR_PCT = float(os.getenv("MIN_ATR_PCT", "0.0035"))                           # Минимум 0.35% 5m ATR (отсев штиля и комиссионной пилы)

MIN_CLOSE_STRENGTH = float(os.getenv("MIN_CLOSE_STRENGTH", "0.68"))
WICK_REJECTION_MIN = float(os.getenv("WICK_REJECTION_MIN", "0.0"))
WICK_EXHAUSTION_MAX = float(os.getenv("WICK_EXHAUSTION_MAX", "0.25"))              # Встречный фитиль истощения <= 25%

# ANTI-RUG TOP GUARD (защита от покупки хая параболы прямо перед дампом!):
MAX_EMA21_EXTENSION_PCT = float(os.getenv("MAX_EMA21_EXTENSION_PCT", "0.045"))     # Не выше 4.5% от EMA21 на сигнальной свече
MAX_PRE_BREAKOUT_EXT_PCT = float(os.getenv("MAX_PRE_BREAKOUT_EXT_PCT", "0.026"))   # За 15 мин (3 бара) до пробоя монета обязана быть в сжатии <= 2.6% от EMA21!
MAX_3H_CLIMAX_RETURN_PCT = float(os.getenv("MAX_3H_CLIMAX_RETURN_PCT", "0.18"))    # Блок входа в выдохшуюся параболу (> +18% за 3 часа)
MAX_LIVE_DRIFT_PCT = float(os.getenv("MAX_LIVE_DRIFT_PCT", "0.014"))

# Волатильно-адаптивные границы стопа (позволяют ракетам дышать; маржа автоматически уменьшается под 3% риска):
STOP_LOSS_MIN_PCT = float(os.getenv("STOP_LOSS_MIN_PCT", "0.0080"))  # 0.80% мин стоп (исключает выбивание шумом и комиссиями)
STOP_LOSS_MAX_PCT = float(os.getenv("STOP_LOSS_MAX_PCT", "0.0350"))  # 3.50% макс стоп (для волатильных ракет вроде GUA/EVAA)
MAX_ALLOWED_SL_PCT = STOP_LOSS_MAX_PCT
SL_ATR_MULT = float(os.getenv("SL_ATR_MULT", "1.60"))                # Структурный стоп не ближе 1.60 * ATR14
SIZING_SL_FLOOR_PCT = float(os.getenv("SIZING_SL_FLOOR_PCT", "0.0080"))
MIN_MARGIN_USDT = float(os.getenv("MIN_MARGIN_USDT", "1.00"))        # Позволяет открывать волатильные ракеты от $1 маржи с честным 3% риском
MIN_MARGIN_EQUITY_PCT = float(os.getenv("MIN_MARGIN_EQUITY_PCT", "0.05"))
MAX_MARGIN_EQUITY_PCT = float(os.getenv("MAX_MARGIN_EQUITY_PCT", "0.25"))
WICK_BUFFER_PCT = float(os.getenv("WICK_BUFFER_PCT", "0.0015"))
MIN_PULLBACK_PCT = float(os.getenv("MIN_PULLBACK_PCT", "0.0005"))

# ==============================================================================
# 5. ANTI-RUG ROCKET HARVEST EXIT (60% В КЭШ ДО СЛИВА + 40% БЕЗРИСКОВЫЙ РАНЕР)
# ==============================================================================
EARLY_BE_TRIGGER_PCT = float(os.getenv("EARLY_BE_TRIGGER_PCT", "9.99"))   # Отключен до TP1: не душим нормальный ретест пробоя
EARLY_BE_TRIGGER_R = float(os.getenv("EARLY_BE_TRIGGER_R", "99.0"))
EARLY_BE_LOCK_PCT = float(os.getenv("EARLY_BE_LOCK_PCT", "0.0022"))

TARGET_1_R = float(os.getenv("TARGET_1_R", "1.65"))          # На +1.65R мгновенно забираем 60% прибыли в кэш (до любого возможного слива!)
TARGET_2_R = float(os.getenv("TARGET_2_R", "6.00"))          # Верхний ориентир супер-ракеты (сопровождается прогрессивным Anti-Rug Ratchet)
TP1_PARTIAL_PCT = float(os.getenv("TP1_PARTIAL_PCT", "0.60")) # 60% в кэш на 1.65R + стоп остатка 40% в +0.35R (сделка 100% безрисковая!)
POST_TP1_LOCK_R = float(os.getenv("POST_TP1_LOCK_R", "0.35"))
MAX_RISK_FREE_RUNNERS = int(os.getenv("MAX_RISK_FREE_RUNNERS", "2"))  # Безрисковые ранеры (после TP1) не блокируют слоты для новых ракет!
TP2_PARTIAL_OF_REMAINING = 1.00

TP1_PCT = float(os.getenv("TP1_PCT", "0.0000"))
TP2_PCT = float(os.getenv("TP2_PCT", "0.0000"))

RUNNER_ATR_MULT = float(os.getenv("RUNNER_ATR_MULT", "1.65"))
RUNNER_ACTIVATION_R = float(os.getenv("RUNNER_ACTIVATION_R", "2.2"))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.0100"))
TIME_STOP_MINUTES = int(os.getenv("TIME_STOP_MINUTES", "0"))  # 0 = отключен (без преждевременного среза позиций)
STAGNATION_EXIT_MINUTES = int(os.getenv("STAGNATION_EXIT_MINUTES", "0"))
TAKER_FEE_PCT = float(os.getenv("TAKER_FEE_PCT", "0.0006"))

# ==============================================================================
# 6. MARKET SCANNER & DYNAMIC LIQUID FUTURES UNIVERSE ($15M+ 24H VOL — БЕЗ ШОР)
# ==============================================================================
MIN_24H_VOLUME_USDT = float(os.getenv("MIN_24H_VOLUME_USDT", "15000000"))                 # От $15M USDT на fapi: охватывает ~90+ живых ракет (GUA, EVAA, LISTA...)
SPOT_MIRROR_MIN_VOL_USDT = float(os.getenv("SPOT_MIRROR_MIN_VOL_USDT", "1200000"))        # $1.2M Spot USDT на vision
SCAN_TICKERS_LIMIT = min(int(os.getenv("SCAN_TICKERS_LIMIT", "150")), 200)                # Проверяем все ликвидные пары целиком
MIN_24H_TRADES_COUNT = int(os.getenv("MIN_24H_TRADES_COUNT", "3500"))
MIN_AVG_5M_QUOTE_VOL = float(os.getenv("MIN_AVG_5M_QUOTE_VOL", "15000.0"))                # Минимум $15K/5m свеча
MIN_V3_VOLUME_PERSISTENCE = float(os.getenv("MIN_V3_VOLUME_PERSISTENCE", "1.15"))         # Кумулятивный приток объема за 3 свечи >= 1.15x
ENABLE_MTF_15M_FILTER = os.getenv("ENABLE_MTF_15M_FILTER", "true").lower() == "true"      # Строгая 15m лента EMA9 > EMA21 > EMA50
MAX_24H_CHANGE_CAP = float(os.getenv("MAX_24H_CHANGE_CAP", "100.0"))
STRICT_WHITELIST_ONLY = os.getenv("STRICT_WHITELIST_ONLY", "false").lower() == "true"     # FALSE: динамический поиск настоящих ракет по всему рынку!
CHOP_MIN_VOLUME_SURGE = float(os.getenv("CHOP_MIN_VOLUME_SURGE", "2.00"))
ML_MIN_FILTER_PROB = float(os.getenv("ML_MIN_FILTER_PROB", "0.0"))                        # ML только для телеметрии (не блокирует валидные 6h ракеты)
ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.50"))

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
PAIR_COOLDOWN_MINUTES = int(os.getenv("PAIR_COOLDOWN_MINUTES", "10"))

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
