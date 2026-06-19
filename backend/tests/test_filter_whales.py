"""
filter_whales — the coarse leaderboard pre-filter.

A trader qualifies when:
  - pnl >= WHALE_MIN_PNL (10_000), AND
  - pnl_margin (pnl/vol) >= WHALE_MIN_PNL_MARGIN (0.05), OR pnl >= 50_000
    (the big-PnL fallback admits high earners even on a thin margin).

pnl_margin is NOT a win rate — see whale/monitor.filter_whales. These tests pin
the qualifying logic and that the attached field is named `pnl_margin`.
"""
from whale.monitor import filter_whales


def _trader(name, pnl, vol):
    return {"userName": name, "pnl": pnl, "vol": vol, "proxyWallet": f"0x{name}"}


def test_low_pnl_rejected():
    # Below WHALE_MIN_PNL regardless of margin.
    out = filter_whales([_trader("small", pnl=5_000, vol=10_000)])
    assert out == []


def test_healthy_margin_qualifies():
    # pnl 20k over 100k vol => margin 0.20 (>= 0.05) and pnl >= 10k.
    out = filter_whales([_trader("good", pnl=20_000, vol=100_000)])
    assert len(out) == 1
    assert out[0]["pnl_margin"] == 0.2


def test_thin_margin_below_fallback_rejected():
    # pnl 12k (>= 10k) but margin 12k/1.2M = 0.01 (< 0.05), and pnl < 50k => out.
    out = filter_whales([_trader("churner", pnl=12_000, vol=1_200_000)])
    assert out == []


def test_thin_margin_but_big_pnl_qualifies_via_fallback():
    # margin 60k/6M = 0.01 (< 0.05) but pnl 60k >= 50k => admitted by fallback.
    out = filter_whales([_trader("whale", pnl=60_000, vol=6_000_000)])
    assert len(out) == 1
    assert out[0]["pnl_margin"] == 0.01


def test_margin_field_name_is_pnl_margin_not_win_rate():
    # Guards the rename: the old misleading key must not reappear.
    out = filter_whales([_trader("good", pnl=20_000, vol=100_000)])
    assert "pnl_margin" in out[0]
    assert "estimated_win_rate" not in out[0]


def test_zero_volume_does_not_crash():
    # vol=0 => margin 0; with pnl < 50k that's a reject, but it must not raise.
    out = filter_whales([_trader("novol", pnl=15_000, vol=0)])
    assert out == []
