from dotenv import load_dotenv
import os

load_dotenv()

WALLET_ADDRESS       = os.getenv("WALLET_ADDRESS")
PRIVATE_KEY          = os.getenv("PRIVATE_KEY")

VIRTUALS_API_KEY     = os.getenv("VIRTUALS_API_KEY")
VIRTUALS_BASE_URL    = os.getenv("VIRTUALS_BASE_URL", "https://compute.virtuals.io/v1")

TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID")

PAPER_MODE           = os.getenv("PAPER_MODE", "true").lower() == "true"
BANKROLL             = float(os.getenv("BANKROLL", "50.0"))
MAX_BET_PCT          = float(os.getenv("MAX_BET_PCT", "0.10"))
KELLY_FRACTION       = float(os.getenv("KELLY_FRACTION", "0.5"))
TAKE_PROFIT_PCT      = float(os.getenv("TAKE_PROFIT_PCT", "0.25"))
STOP_LOSS_PCT        = float(os.getenv("STOP_LOSS_PCT", "0.20"))
MIN_EDGE             = float(os.getenv("MIN_EDGE", "0.08"))
MIN_CLAUDE_SCORE     = int(os.getenv("MIN_CLAUDE_SCORE", "7"))
MAX_OPEN_POSITIONS   = int(os.getenv("MAX_OPEN_POSITIONS", "8"))

WHALE_MIN_PNL        = float(os.getenv("WHALE_MIN_PNL", "10000"))
WHALE_MIN_WIN_RATE   = float(os.getenv("WHALE_MIN_WIN_RATE", "0.70"))
COPY_MAX_DELAY_SECS  = int(os.getenv("COPY_MAX_DELAY_SECONDS", "300"))

# Multi-whale consensus filter
CONSENSUS_MIN_WHALES = int(os.getenv("CONSENSUS_MIN_WHALES", "3"))
CONSENSUS_WINDOW_SECS = int(os.getenv("CONSENSUS_WINDOW_HOURS", "4")) * 3600

# Enhanced Kelly / risk
DRAWDOWN_BREAKER_PCT = float(os.getenv("DRAWDOWN_BREAKER_PCT", "0.15"))
PEAK_BANKROLL        = float(os.getenv("PEAK_BANKROLL", str(BANKROLL)))
MAX_SAME_DAY_RESOLUTIONS = int(os.getenv("MAX_SAME_DAY_RESOLUTIONS", "3"))
MAX_YES_CONCENTRATION = float(os.getenv("MAX_YES_CONCENTRATION", "0.60"))

SCAN_INTERVAL        = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))
POSITION_CHECK_SECS  = int(os.getenv("POSITION_CHECK_SECONDS", "600"))

DATA_API   = "https://data-api.polymarket.com"
GAMMA_API  = "https://gamma-api.polymarket.com"
CLOB_API   = "https://clob.polymarket.com"
CHAIN_ID   = 137

BLOCK_CATEGORIES = {"sports", "esports", "counter-strike", "football", "basketball", "tennis"}
