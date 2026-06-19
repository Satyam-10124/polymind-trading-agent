import logging
from config import PRIVATE_KEY, WALLET_ADDRESS, CHAIN_ID, CLOB_API, PAPER_MODE, SLIPPAGE_BPS

logger = logging.getLogger(__name__)

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.constants import POLYGON
    _clob_available = True
except ImportError:
    _clob_available = False
    logger.warning("py-clob-client not installed — executor in mock mode")


def _get_client():
    if not _clob_available:
        return None
    try:
        client = ClobClient(
            host      = CLOB_API,
            chain_id  = CHAIN_ID,
            key       = PRIVATE_KEY,
            funder    = WALLET_ADDRESS,
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        return client
    except Exception as e:
        logger.error(f"CLOB client init failed: {e}")
        return None


_client = None


def get_client():
    global _client
    if _client is None:
        _client = _get_client()
    return _client


def sell_limit_price(current_price: float) -> float:
    """
    Limit price for an exit SELL: market price reduced by SLIPPAGE_BPS so the
    order crosses and fills, expressed in basis points rather than a flat ±$0.01
    (which is 2% of a 50¢ market but 10% of a 10¢ one). Floored at the CLOB
    minimum tick (0.01).
    """
    return max(round(current_price * (1 - SLIPPAGE_BPS / 10_000), 4), 0.01)


def place_order(token_id: str, side: str, size: float, price: float) -> dict:
    log_msg = (
        f"{'[PAPER] ' if PAPER_MODE else ''}Order: {side} {size:.2f} USDC "
        f"of token {token_id[:12]}... @ {price:.4f}"
    )
    logger.info(log_msg)

    if PAPER_MODE:
        return {
            "status": "paper",
            "token_id": token_id,
            "side": side,
            "size": size,
            "price": price,
            "order_id": f"paper_{token_id[:8]}",
        }

    client = get_client()
    if not client:
        return {"status": "error", "message": "CLOB client unavailable"}

    try:
        from py_clob_client.clob_types import BUY, SELL
        # Entering a position is always a BUY on the outcome's own token_id.
        # jobs.py already selects the correct token_id for YES vs NO, so a NO
        # entry is a BUY on the NO token — NOT a SELL on the YES token. (SELL is
        # only for exits, handled in sell_position.) See docs/polymarket-buy-sell.md.
        clob_side = BUY
        order_args = OrderArgs(
            token_id  = token_id,
            price     = price,
            size      = size,
            side      = clob_side,
        )
        result = client.create_and_post_order(order_args)
        logger.info(f"Order placed: {result}")
        return {"status": "filled", "order_id": result.get("orderID"), "data": result}
    except Exception as e:
        logger.error(f"Order placement failed: {e}")
        return {"status": "error", "message": str(e)}


def sell_position(token_id: str, shares: float, current_price: float) -> dict:
    logger.info(
        f"{'[PAPER] ' if PAPER_MODE else ''}Sell: {shares:.4f} shares "
        f"of {token_id[:12]}... @ {current_price:.4f}"
    )

    if PAPER_MODE:
        return {
            "status": "paper_sell",
            "token_id": token_id,
            "shares": shares,
            "price": current_price,
        }

    client = get_client()
    if not client:
        return {"status": "error", "message": "CLOB client unavailable"}

    try:
        from py_clob_client.clob_types import SELL
        order_args = OrderArgs(
            token_id = token_id,
            price    = sell_limit_price(current_price),
            size     = shares,
            side     = SELL,
        )
        result = client.create_and_post_order(order_args)
        return {"status": "sold", "data": result}
    except Exception as e:
        logger.error(f"Sell failed: {e}")
        return {"status": "error", "message": str(e)}


def get_wallet_balance() -> float:
    if PAPER_MODE:
        return 50.0
    client = get_client()
    if not client:
        return 0.0
    try:
        return float(client.get_balance())
    except Exception:
        return 0.0
