"""
sell_limit_price — exit SELL limit is set in basis points, not a flat ±$0.01.

The old `max(current_price - 0.01, 0.01)` was 200 bps on a 50¢ market but 1000
bps on a 10¢ one. The bps form gives a constant haircut at every price level:
    limit = current_price * (1 - SLIPPAGE_BPS / 10_000), floored at 0.01.
"""
import pytest

from config import SLIPPAGE_BPS
from executor.clob_client import sell_limit_price


@pytest.mark.parametrize("price", [0.10, 0.25, 0.50, 0.75, 0.95])
def test_limit_is_within_configured_bps(price):
    lp = sell_limit_price(price)
    # The limit sits below market by SLIPPAGE_BPS (allow tiny rounding from the
    # 4-decimal price tick).
    reduction_bps = (price - lp) / price * 10_000
    assert reduction_bps == pytest.approx(SLIPPAGE_BPS, abs=2.0)
    assert lp < price


def test_limit_never_exceeds_configured_bps():
    # Never give away MORE than the configured slippage (modulo a tick of rounding).
    for price in (0.10, 0.33, 0.50, 0.88):
        lp = sell_limit_price(price)
        max_haircut = price * (SLIPPAGE_BPS / 10_000) + 0.0001  # +1 tick tolerance
        assert (price - lp) <= max_haircut


def test_floored_at_min_tick():
    # A sub-penny market can't price below the 0.01 CLOB minimum tick.
    assert sell_limit_price(0.005) == 0.01


def test_scales_with_price_unlike_flat_offset():
    # The whole point: haircut is proportional, so the bps reduction at 10c and
    # 50c match (the old flat $0.01 would have been 5x worse at 10c).
    bps_10 = (0.10 - sell_limit_price(0.10)) / 0.10 * 10_000
    bps_50 = (0.50 - sell_limit_price(0.50)) / 0.50 * 10_000
    assert bps_10 == pytest.approx(bps_50, abs=2.0)
