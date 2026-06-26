import logging
import requests
from datetime import datetime, timezone
from config import TAKE_PROFIT_PCT, STOP_LOSS_PCT, CLOB_API

logger = logging.getLogger(__name__)


def get_current_price(token_id: str) -> float | None:
    try:
        r = requests.get(
            f"{CLOB_API}/price",
            params={"token_id": token_id, "side": "sell"},
            timeout=8,
        )
        r.raise_for_status()
        return float(r.json().get("price", 0))
    except Exception as e:
        logger.error(f"Price fetch for {token_id}: {e}")
        return None


def check_position(position: dict) -> str:
    """
    Returns: 'hold' | 'take_profit_partial' | 'take_profit_full' | 'stop_loss' | 'time_stop'
    """
    token_id    = position.get("token_id")
    entry_price = float(position.get("entry_price", 0.5))
    opened_at   = position.get("opened_at")

    current = get_current_price(token_id)
    if current is None:
        return "hold"

    pnl_pct = (current - entry_price) / entry_price

    if pnl_pct >= TAKE_PROFIT_PCT * 2:
        logger.info(f"TAKE PROFIT FULL: {position.get('question','?')[:50]} PnL={pnl_pct:+.1%}")
        return "take_profit_full"

    # Only offer the partial tier if it hasn't already fired for this position.
    if pnl_pct >= TAKE_PROFIT_PCT and not int(position.get("partial_tp_done", 0)):
        logger.info(f"TAKE PROFIT PARTIAL: {position.get('question','?')[:50]} PnL={pnl_pct:+.1%}")
        return "take_profit_partial"

    if pnl_pct <= -STOP_LOSS_PCT:
        logger.info(f"STOP LOSS: {position.get('question','?')[:50]} PnL={pnl_pct:+.1%}")
        return "stop_loss"

    if opened_at:
        try:
            dt = datetime.fromisoformat(str(opened_at).replace("Z", "+00:00"))
            days_held = (datetime.now(timezone.utc) - dt).days
            if days_held >= 21:
                logger.info(f"TIME STOP (21d): {position.get('question','?')[:50]}")
                return "time_stop"
        except Exception:
            pass

    return "hold"


def compute_pnl(position: dict) -> float:
    token_id    = position.get("token_id")
    entry_price = float(position.get("entry_price", 0.5))
    size        = float(position.get("size", 0))
    shares      = size / entry_price if entry_price > 0 else 0
    current     = get_current_price(token_id) or entry_price
    return (current - entry_price) * shares
