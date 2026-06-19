"""
Execution cost model.

Whale-following strategies live or die on slippage: you are, by construction,
trading *after* an informed actor moved the price, into a book that may be thin.
The backtest must therefore never assume a fill at the observed mid. We charge:

  - half the spread (FILL_SPREAD_BPS) — you cross to the ask on a buy,
  - plus market-impact slippage (SLIPPAGE_BPS) — scaled mildly by order size.

Both are expressed in basis points of price and pushed *against* the trader
(buys fill higher, sells fill lower).
"""
from config import SLIPPAGE_BPS, FILL_SPREAD_BPS


def apply_slippage(price: float, side: str, size_usdc: float = 0.0,
                   slippage_bps: float | None = None,
                   spread_bps: float | None = None) -> float:
    """
    Returns the realistic fill price for `side`. A buy fills higher than `price`;
    a sell fills lower. Size adds a small extra impact term (10% more slippage per
    $1k of notional, capped at 3x base).

    Entries are buys regardless of outcome: both YES and NO entries are a BUY on
    the respective outcome token (see docs/polymarket-buy-sell.md), so only an
    explicit SELL (an exit) fills lower.
    """
    slip = (slippage_bps if slippage_bps is not None else SLIPPAGE_BPS) / 10_000.0
    spread = (spread_bps if spread_bps is not None else FILL_SPREAD_BPS) / 10_000.0

    size_mult = min(3.0, 1.0 + (size_usdc / 1000.0) * 0.10)
    total = spread + slip * size_mult

    is_buy = side.upper() != "SELL"
    fill = price * (1 + total) if is_buy else price * (1 - total)
    return max(0.001, min(0.999, fill))
