import logging
from config import PRIVATE_KEY, WALLET_ADDRESS, CHAIN_ID, CLOB_API, PAPER_MODE

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
        clob_side = BUY if side.upper() == "YES" else SELL
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
            price    = max(current_price - 0.01, 0.01),
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
