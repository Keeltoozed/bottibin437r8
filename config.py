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
INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "100.0"))

# Режим сайзинга: equal_margin ("как они" — равный залог маржи на каждую сделку!) или risk_parity
SIZING_MODE = os.getenv("SIZING_MODE", "equal_margin")
FIXED_MARGIN_PCT = float(os.getenv("FIXED_MARGIN_PCT", "0.030"))  # 3.0% от эквити ($3.00 маржа / $150.00 позиция @ 50x Cross при $100!)

# Параметры Risk-Parity (используются только при SIZING_MODE=risk_parity) и защиты от просадки:
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.055"))
CONVICTION_RISK_MULT = float(os.getenv("CONVICTION_RISK_MULT", "1.00"))
DD_GUARD_THRESHOLD = float(os.getenv("DD_GUARD_THRESHOLD", "0.20"))
DD_GUARD_RISK_MULT = float(os.getenv("DD_GUARD_RISK_MULT", "0.75"))
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "10.0"))
MAX_CONCURRENT_POSITIONS = min(int(os.getenv("MAX_POSITIONS", "8")), 10)
LEVERAGE = int(os.getenv("LEVERAGE", "50"))
ENABLE_SHORT = os.getenv("ENABLE_SHORT", "true").lower() == "true"

# Предохранитель депозита (Circuit Breaker):
# По запросу пользователя заморозка торговли при серии минусов ОТКЛЮЧЕНА (бот торгует непрерывно 24/7):
ENABLE_CIRCUIT_BREAKER = os.getenv("ENABLE_CIRCUIT_BREAKER", "false").lower() == "true"
DAILY_LOSS_LIMIT = int(os.getenv("DAILY_LOSS_LIMIT", "99"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "99"))
CONSECUTIVE_LOSS_PAUSE_SECONDS = int(os.getenv("CONSECUTIVE_LOSS_PAUSE_SECONDS", "0"))  # Без пауз заморозки
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "999.00"))

# ==============================================================================
# 4. ALPHA ROCKET ENGINE (RS vs BTC + 3H/80M SQUEEZE + RUG-SHORT — 7/7 SPLITS!)
# ==============================================================================
BREAKOUT_LOOKBACK_BARS = int(os.getenv("BREAKOUT_LOOKBACK_BARS", "36"))   # Пробой 3-часовой структуры (36 x 5m баров — ранний вход в ракету!)
SQUEEZE_LOOKBACK_BARS = int(os.getenv("SQUEEZE_LOOKBACK_BARS", "16"))     # Быстрый старт из 80-мин сжатия (диапазон <= 6.5%)
SQUEEZE_MAX_RANGE_PCT = float(os.getenv("SQUEEZE_MAX_RANGE_PCT", "0.065"))
SQUEEZE_MIN_RVOL = float(os.getenv("SQUEEZE_MIN_RVOL", "2.00"))
ENABLE_RUG_HUNTER_SHORT = os.getenv("ENABLE_RUG_HUNTER_SHORT", "true").lower() == "true"  # Перехват сливов после пампа >= +15%
RUG_PUMP_MIN_PCT = float(os.getenv("RUG_PUMP_MIN_PCT", "0.15"))
RUG_SUPPORT_BARS = int(os.getenv("RUG_SUPPORT_BARS", "16"))

# ФИЛЬТР ОТНОСИТЕЛЬНОЙ СИЛЫ ПРОТИВ BTC (IDIOSYNCRATIC ALPHA vs BETA):
# Монета обязана двигаться САМА значительно сильнее BTC — полностью отсекает ложные синхронные проливы типа 14:35 UTC!
MIN_ALPHA_5M_PCT = float(os.getenv("MIN_ALPHA_5M_PCT", "0.80"))    # |coin_5m - btc_5m| >= 0.80%
MIN_ALPHA_15M_PCT = float(os.getenv("MIN_ALPHA_15M_PCT", "1.00"))  # |coin_15m - btc_15m| >= 1.00%

FAST_IGNITION_LOOKBACK_BARS = int(os.getenv("FAST_IGNITION_LOOKBACK_BARS", "36"))
FAST_IGNITION_SURGE = float(os.getenv("FAST_IGNITION_SURGE", "99.0"))
CONTINUATION_LOOKBACK_BARS = int(os.getenv("CONTINUATION_LOOKBACK_BARS", "36"))
ENABLE_FLAG_CONTINUATION = os.getenv("ENABLE_FLAG_CONTINUATION", "false").lower() == "true"
ENABLE_LIVE_INTRABAR_IGNITION = os.getenv("ENABLE_LIVE_INTRABAR_IGNITION", "false").lower() == "true"

MIN_5M_VOLUME_SURGE_RATIO = float(os.getenv("MIN_5M_VOLUME_SURGE_RATIO", "1.80"))  # Всплеск RVOL >= 1.80x к 20-свечной средней
MIN_VOLUME_SURGE = MIN_5M_VOLUME_SURGE_RATIO
MIN_5M_PRICE_IMPULSE_PCT = float(os.getenv("MIN_5M_PRICE_IMPULSE_PCT", "0.55"))    # Чистый импульс >= 0.55% (и >= 0.85 * ATR14)
MIN_IMPULSE_PCT = MIN_5M_PRICE_IMPULSE_PCT
MIN_ATR_PCT = float(os.getenv("MIN_ATR_PCT", "0.0025"))                           # Минимум 0.25% 5m ATR (работает и на fapi, и на vision)

MIN_CLOSE_STRENGTH = float(os.getenv("MIN_CLOSE_STRENGTH", "0.66"))
WICK_REJECTION_MIN = float(os.getenv("WICK_REJECTION_MIN", "0.0"))
WICK_EXHAUSTION_MAX = float(os.getenv("WICK_EXHAUSTION_MAX", "0.26"))              # Встречный фитиль истощения <= 26%

# ANTI-RUG TOP GUARD & ANTI-SPIKE (защита от покупки вертикального спайка и хая параболы перед откатом!):
MAX_ENTRY_5M_SPIKE_PCT = float(os.getenv("MAX_ENTRY_5M_SPIKE_PCT", "3.50"))  # Блок выдохшихся 5m свечей > 3.5% (PF 1.65->1.78, DD 31.2%->28.3%!)
MAX_EMA21_EXTENSION_PCT = float(os.getenv("MAX_EMA21_EXTENSION_PCT", "0.048"))     # Не выше 4.8% от EMA21 на сигнальной свече
MAX_PRE_BREAKOUT_EXT_PCT = float(os.getenv("MAX_PRE_BREAKOUT_EXT_PCT", "0.028"))   # За 15 мин (3 бара) до пробоя монета была в базе <= 2.8% от EMA21!
MAX_3H_CLIMAX_RETURN_PCT = float(os.getenv("MAX_3H_CLIMAX_RETURN_PCT", "0.20"))    # Блок входа в выдохшуюся параболу (> +20% за 3 часа)
MAX_LIVE_DRIFT_PCT = float(os.getenv("MAX_LIVE_DRIFT_PCT", "0.018"))

# Волатильно-адаптивные границы стопа (простор под Big-Runner удержание: мин 1.1%, макс 4.5%, ATR x1.75 — не сносит шумом!):
STOP_LOSS_MIN_PCT = float(os.getenv("STOP_LOSS_MIN_PCT", "0.0110"))  # 1.10% мин стоп (защита от шумовых сбивов)
STOP_LOSS_MAX_PCT = float(os.getenv("STOP_LOSS_MAX_PCT", "0.0450"))  # 4.50% макс стоп (контроль риска на Cross Margin!)
MAX_ALLOWED_SL_PCT = STOP_LOSS_MAX_PCT
SL_ATR_MULT = float(os.getenv("SL_ATR_MULT", "1.75"))                # Структурный стоп не ближе 1.75 * ATR14
SIZING_SL_FLOOR_PCT = float(os.getenv("SIZING_SL_FLOOR_PCT", "0.0110"))
MIN_MARGIN_USDT = float(os.getenv("MIN_MARGIN_USDT", "0.50"))
MIN_MARGIN_EQUITY_PCT = float(os.getenv("MIN_MARGIN_EQUITY_PCT", "0.04"))
MAX_MARGIN_EQUITY_PCT = float(os.getenv("MAX_MARGIN_EQUITY_PCT", "0.30"))
ENABLE_SM_FVG_ENTRY = os.getenv("ENABLE_SM_FVG_ENTRY", "true").lower() == "true"  # Входы Smart Money (16b BOS + FVG + EMA200 + ADX>=20)
FVG_EMA200_SCORE_BOOST = float(os.getenv("FVG_EMA200_SCORE_BOOST", "1.25"))       # Приоритет ракетам с FVG + трендом EMA200
ADX_TREND_SCORE_BOOST = float(os.getenv("ADX_TREND_SCORE_BOOST", "1.15"))         # Приоритет трендовым пробоям (ADX >= 20)
WICK_BUFFER_PCT = float(os.getenv("WICK_BUFFER_PCT", "0.0015"))
MIN_PULLBACK_PCT = float(os.getenv("MIN_PULLBACK_PCT", "0.0005"))

# ==============================================================================
# 5. ANTI-RUG ROCKET HARVEST EXIT (60% В КЭШ ДО СЛИВА + 40% БЕЗРИСКОВЫЙ РАНЕР)
# ==============================================================================
EARLY_BE_TRIGGER_PCT = float(os.getenv("EARLY_BE_TRIGGER_PCT", "9.99"))   # Отключен до TP1: не душим нормальный ретест пробоя
EARLY_BE_TRIGGER_R = float(os.getenv("EARLY_BE_TRIGGER_R", "99.0"))
EARLY_BE_LOCK_PCT = float(os.getenv("EARLY_BE_LOCK_PCT", "0.0022"))

TARGET_1_R = float(os.getenv("TARGET_1_R", "1.90"))          # Дальний TP1 (+1.90R): 35% в кэш, не режем ракету рано!
TARGET_2_R = float(os.getenv("TARGET_2_R", "8.00"))          # Верхний ориентир супер-ракеты (+350%..+700%+ @ 50x)
TP1_PARTIAL_PCT = float(os.getenv("TP1_PARTIAL_PCT", "0.35")) # 35% в кэш на TP1 + 25% на TP2 -> 40% летит в Big-Runner Moonbag!
POST_TP1_LOCK_R = float(os.getenv("POST_TP1_LOCK_R", "0.40"))
MAX_RISK_FREE_RUNNERS = int(os.getenv("MAX_RISK_FREE_RUNNERS", "4"))  # Безрисковые ранеры (после TP1) не блокируют слоты для новых ракет!
TP2_PARTIAL_OF_REMAINING = 1.00

TP1_PCT = float(os.getenv("TP1_PCT", "0.0000"))
TP2_PCT = float(os.getenv("TP2_PCT", "0.0000"))

RUNNER_ATR_MULT = float(os.getenv("RUNNER_ATR_MULT", "2.25"))
RUNNER_ACTIVATION_R = float(os.getenv("RUNNER_ACTIVATION_R", "3.1"))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.0100"))
TIME_STOP_MINUTES = int(os.getenv("TIME_STOP_MINUTES", "0"))  # 0 = ранний срез отключен (не режет нормальный ретест)
TTL_HOURS = int(os.getenv("TTL_HOURS", "24"))                  # Максимальное время жизни сделки без TP1 (24ч высвобождает слоты под новые ракеты)
STAGNATION_EXIT_MINUTES = int(os.getenv("STAGNATION_EXIT_MINUTES", "0"))
TAKER_FEE_PCT = float(os.getenv("TAKER_FEE_PCT", "0.0006"))

# ==============================================================================
# 6. 500-COIN FULL-MARKET RADAR + SMART PRE-FILTER (ВСЕ КРИПТО-ПЕРПЫ + НОВЫЕ ЛИСТИНГИ!)
# ==============================================================================
MIN_24H_VOLUME_USDT = float(os.getenv("MIN_24H_VOLUME_USDT", "1500000"))                  # От $1.5M + авто-добор от $250K (охват 400-500+ крипто-пар!)
ALT_FUTURES_MIN_VOL_USDT = float(os.getenv("ALT_FUTURES_MIN_VOL_USDT", "350000"))         # $350K+ на Bybit/Gate/Bitget (до 450+ чистых перпов)
BITGET_MIRROR_MIN_VOL_USDT = ALT_FUTURES_MIN_VOL_USDT
SPOT_MIRROR_MIN_VOL_USDT = float(os.getenv("SPOT_MIRROR_MIN_VOL_USDT", "350000"))
SCAN_TICKERS_LIMIT = min(int(os.getenv("SCAN_TICKERS_LIMIT", "240")), 300)                # Топ-240 самых горячих из 400-500+ пар на глубокий анализ свечей!
MIN_24H_TRADES_COUNT = int(os.getenv("MIN_24H_TRADES_COUNT", "1000"))
SPOT_MIRROR_MIN_TRADES = int(os.getenv("SPOT_MIRROR_MIN_TRADES", "600"))
MIN_AVG_5M_QUOTE_VOL = float(os.getenv("MIN_AVG_5M_QUOTE_VOL", "2500.0"))                 # $2.5K/5m база (+ >=$8K пробойная свеча) на fapi
ALT_FUTURES_MIN_AVG_5M_VOL = float(os.getenv("ALT_FUTURES_MIN_AVG_5M_VOL", "600.0"))      # $600/5m база (+ >=$2.5K пробойная свеча) на Bybit/Gate/Bitget
BITGET_MIRROR_MIN_AVG_5M_VOL = ALT_FUTURES_MIN_AVG_5M_VOL
SPOT_MIRROR_MIN_AVG_5M_VOL = float(os.getenv("SPOT_MIRROR_MIN_AVG_5M_VOL", "500.0"))
MIN_V3_VOLUME_PERSISTENCE = float(os.getenv("MIN_V3_VOLUME_PERSISTENCE", "1.10"))         # Кумулятивный приток объема за 3 свечи >= 1.10x
ENABLE_MTF_15M_FILTER = os.getenv("ENABLE_MTF_15M_FILTER", "true").lower() == "true"      # Строгая 15m лента EMA9 > EMA21 > EMA50
MAX_24H_CHANGE_CAP = float(os.getenv("MAX_24H_CHANGE_CAP", "120.0"))
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
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.0030"))  # 0.30% max spread (учитывает тик-шаг дешевых мемов на Spot/Vision зеркале)
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
