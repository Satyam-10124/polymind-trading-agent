"""
Slippage model — direction handling.

Entries are buys regardless of outcome: both YES and NO entries are a BUY on the
respective outcome token (see docs/polymarket-buy-sell.md), so they fill HIGHER
than the observed price. Only an explicit SELL (an exit) fills LOWER.
"""
from feed.slippage import apply_slippage


def test_yes_buy_fills_higher():
    fill = apply_slippage(0.40, "YES")
    assert fill > 0.40, f"YES buy should fill higher than 0.40, got {fill}"


def test_no_buy_fills_higher():
    # The bug being guarded against: NO was treated as a sell and filled lower.
    fill = apply_slippage(0.60, "NO")
    assert fill > 0.60, f"NO buy should fill higher than 0.60, got {fill}"


def test_exit_sell_fills_lower():
    fill = apply_slippage(0.60, "SELL")
    assert fill < 0.60, f"exit SELL should fill lower than 0.60, got {fill}"
