"""
LiveExecutor — adapts the existing executor.clob_client (real CLOB in live mode,
mock fills in paper mode) to the Executor interface so jobs.py can hold an
Executor reference that is identical in shape to the SimExecutor used in backtests.
"""
import logging
from feed.base import Executor, Fill
from executor.clob_client import place_order, sell_position

logger = logging.getLogger(__name__)


class LiveExecutor(Executor):
    def buy(self, token_id: str, side: str, size: float, price: float) -> Fill:
        res = place_order(token_id, side, size, price)
        status = res.get("status", "error")
        fill_price = float(res.get("price", price) or price)
        shares = size / fill_price if fill_price > 0 else 0.0
        return Fill(
            status=status, token_id=token_id, side=side, size=size,
            requested_price=price, fill_price=fill_price, shares=shares,
            slippage=fill_price - price, order_id=res.get("order_id", ""),
            message=res.get("message", ""),
        )

    def sell(self, token_id: str, shares: float, price: float) -> Fill:
        res = sell_position(token_id, shares, price)
        status = res.get("status", "error")
        fill_price = float(res.get("price", price) or price)
        return Fill(
            status=status, token_id=token_id, side="SELL", size=shares * fill_price,
            requested_price=price, fill_price=fill_price, shares=shares,
            slippage=fill_price - price, order_id=res.get("order_id", ""),
            message=res.get("message", ""),
        )
