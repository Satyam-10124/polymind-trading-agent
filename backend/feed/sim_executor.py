"""
Simulated executor for backtests. Fills against a modeled price with slippage,
never touching the network. Mirrors the LiveExecutor interface so the strategy
code is identical in both paths.
"""
import logging
from feed.base import Executor, Fill
from feed.slippage import apply_slippage

logger = logging.getLogger(__name__)


class SimExecutor(Executor):
    def __init__(self, slippage_bps: float | None = None, spread_bps: float | None = None):
        self.slippage_bps = slippage_bps
        self.spread_bps = spread_bps
        self.fills: list[Fill] = []

    def buy(self, token_id: str, side: str, size: float, price: float) -> Fill:
        fill_price = apply_slippage(price, side, size, self.slippage_bps, self.spread_bps)
        shares = size / fill_price if fill_price > 0 else 0.0
        fill = Fill(
            status="filled", token_id=token_id, side=side, size=size,
            requested_price=price, fill_price=round(fill_price, 4), shares=shares,
            slippage=round(fill_price - price, 4), order_id=f"sim_{token_id[:8]}",
        )
        self.fills.append(fill)
        return fill

    def sell(self, token_id: str, shares: float, price: float) -> Fill:
        fill_price = apply_slippage(price, "SELL", shares * price, self.slippage_bps, self.spread_bps)
        fill = Fill(
            status="filled", token_id=token_id, side="SELL", size=shares * fill_price,
            requested_price=price, fill_price=round(fill_price, 4), shares=shares,
            slippage=round(fill_price - price, 4), order_id=f"sim_{token_id[:8]}",
        )
        self.fills.append(fill)
        return fill
