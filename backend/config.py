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
# Profit margin per dollar traded (pnl / vol) — a coarse "this trader actually
# makes money" gate at leaderboard time. NOT a win rate: the leaderboard only
# exposes pnl and vol, never win/loss counts. The real win rate is computed
# downstream from trade history in whale/profiler.py when a whale actually trades.
WHALE_MIN_PNL_MARGIN = float(os.getenv("WHALE_MIN_PNL_MARGIN", "0.05"))
COPY_MAX_DELAY_SECS  = int(os.getenv("COPY_MAX_DELAY_SECONDS", "300"))

# Recency filter: a whale top-ranked by ALL-TIME PnL may have blown up recently.
# Drop anyone whose PnL over the trailing WHALE_RECENCY_DAYS is negative. Results
# are cached per wallet for WHALE_RECENCY_CACHE_SECS (aggressive — the recent-PnL
# signal barely moves between scans, and /activity is rate-limited).
WHALE_RECENCY_DAYS        = int(os.getenv("WHALE_RECENCY_DAYS", "90"))
WHALE_RECENCY_CACHE_SECS  = int(os.getenv("WHALE_RECENCY_CACHE_SECONDS", str(6 * 3600)))
WHALE_RECENCY_FETCH_LIMIT = int(os.getenv("WHALE_RECENCY_FETCH_LIMIT", "200"))

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
WS_URL     = os.getenv("CLOB_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws")
CHAIN_ID   = 137

BLOCK_CATEGORIES = {"sports", "esports", "counter-strike", "football", "basketball", "tennis"}

# ── Committee model cascade ───────────────────────────────────
# Each agent runs on the cheapest tier that does its job well. CRO red-team and
# the final committee vote (the adversarial / judgment calls) stay on Opus; the
# structured-extraction agents drop to Sonnet; pure classification to Haiku.
# Override any of these via env if the Virtuals API rejects a given model id.
MODEL_OPUS    = os.getenv("MODEL_OPUS", "claude-opus-4-5")
MODEL_SONNET  = os.getenv("MODEL_SONNET", "claude-sonnet-4-6")
MODEL_HAIKU   = os.getenv("MODEL_HAIKU", "claude-haiku-4-5")

COMMITTEE_MODELS = {
    "whale_intent": os.getenv("MODEL_WHALE_INTENT", MODEL_SONNET),
    "efficiency":   os.getenv("MODEL_EFFICIENCY",   MODEL_SONNET),
    "archetype":    os.getenv("MODEL_ARCHETYPE",    MODEL_HAIKU),
    "cro":          os.getenv("MODEL_CRO",          MODEL_OPUS),
    "portfolio":    os.getenv("MODEL_PORTFOLIO",    MODEL_SONNET),
    "sizing":       os.getenv("MODEL_SIZING",       MODEL_SONNET),
    "committee":    os.getenv("MODEL_COMMITTEE",    MODEL_OPUS),
    "post_mortem":  os.getenv("MODEL_POST_MORTEM",  MODEL_SONNET),
}
# Run the three independent first-stage agents concurrently to cut decision latency.
COMMITTEE_PARALLEL = os.getenv("COMMITTEE_PARALLEL", "true").lower() == "true"

# ── Real-time feed ────────────────────────────────────────────
# When true, a WebSocket consumer pushes fresh whale trades event-driven and the
# periodic polling scan only refreshes the whale (leaderboard) set. Falls back to
# polling automatically if the socket can't connect.
USE_WEBSOCKET        = os.getenv("USE_WEBSOCKET", "false").lower() == "true"
WHALE_REFRESH_SECS   = int(os.getenv("WHALE_REFRESH_SECONDS", "300"))

# ── Probability calibration ───────────────────────────────────
# Shrink the committee's stated probability toward the market price, weighted by
# its own historical calibration and the consensus strength, before Kelly sizing.
CALIBRATION_ENABLED  = os.getenv("CALIBRATION_ENABLED", "true").lower() == "true"
CALIBRATION_MIN_SAMPLES = int(os.getenv("CALIBRATION_MIN_SAMPLES", "20"))
MAX_PROB_DEVIATION   = float(os.getenv("MAX_PROB_DEVIATION", "0.15"))  # cap edge claim

# ── Backtest / execution realism ──────────────────────────────
SLIPPAGE_BPS         = float(os.getenv("SLIPPAGE_BPS", "150"))   # modeled entry slippage
FILL_SPREAD_BPS      = float(os.getenv("FILL_SPREAD_BPS", "100")) # half-spread paid on entry
