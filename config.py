import os
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# 1. GROQ AI ENGINE CONFIG (JEV ENGINE)
# ==============================================================================
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")
GROQ_PRIMARY_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
GROQ_FALLBACK_MODEL = os.getenv("GROQ_MODEL_FALLBACK", "openai/gpt-oss-20b").strip()
GROQ_RPM_LIMIT = int(os.getenv("GROQ_RPM_LIMIT", "25"))  # Safe rate limit for free tier (max 30 RPM)
GROQ_MIN_CONFIDENCE = float(os.getenv("GROQ_MIN_CONFIDENCE", "0.65"))

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
# 3. TRADING & RISK MANAGEMENT ($20 BANKROLL)
# ==============================================================================
# Paper trading is enabled by default for safe real-market testing
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "20.0"))

# For $20 capital: $5 margin per position allows up to 3 positions with $5 cash reserve
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "5.0"))
LEVERAGE = int(os.getenv("LEVERAGE", "5"))
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))

# ==============================================================================
# 4. EXIT STRATEGY & "THE LINE" (GROK x JEV RULES)
# ==============================================================================
# "We bid the flush, not the candle": pullback required before entry
MIN_PULLBACK_PCT = float(os.getenv("MIN_PULLBACK_PCT", "0.003"))  # 0.3% pullback

# "The stop lives under the wick": wick buffer (0.15% below the candle's low wick)
WICK_BUFFER_PCT = float(os.getenv("WICK_BUFFER_PCT", "0.0015"))
MAX_ALLOWED_SL_PCT = float(os.getenv("MAX_ALLOWED_SL_PCT", "0.035"))  # Max 3.5% SL

# Multi-tier Take Profit
TP1_PCT = float(os.getenv("TP1_PCT", "0.022"))  # +2.2% -> close 50% & move to breakeven
TP2_PCT = float(os.getenv("TP2_PCT", "0.045"))  # +4.5% -> close 25%
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.012"))  # 1.2% trailing off high

# Breakeven trigger: move SL to entry when 50% of distance to TP1 is reached
BREAKEVEN_TRIGGER_RATIO = 0.50

# Momentum Death: early exit if 1m volume collapses and price stalls
ENABLE_MOMENTUM_DEATH_EXIT = True

# ==============================================================================
# 5. MARKET SCANNER & THE FUNNEL (HARD GATES)
# ==============================================================================
MIN_24H_VOLUME_USDT = float(os.getenv("MIN_24H_VOLUME_USDT", "15000000"))  # $15M
MIN_5M_VOLUME_SURGE_RATIO = float(os.getenv("MIN_5M_VOLUME_SURGE_RATIO", "1.6"))  # 1.6x avg vol
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.001"))  # 0.1% max spread
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "12"))
PAIR_COOLDOWN_MINUTES = int(os.getenv("PAIR_COOLDOWN_MINUTES", "8"))

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

