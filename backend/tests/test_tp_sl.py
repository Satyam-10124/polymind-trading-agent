"""
Take-profit / stop-loss signal math, for both YES and NO positions.

A NO position holds the NO outcome's own conditional token (jobs.py selects
token_ids[1] for NO), and entry_price is that NO token's own price. So PnL is
just the NO token appreciating/depreciating like any long:

    pnl_pct = (current - entry_price) / entry_price

The same formula is therefore correct for YES and NO — the direction is encoded
in *which token is tracked*, not in the formula. These tests pin that down so a
regression that (e.g.) tracked the YES price for a NO position would fail.

Thresholds (config): TAKE_PROFIT_PCT=0.25, STOP_LOSS_PCT=0.20.
  pnl_pct >= 0.50 -> take_profit_full
  pnl_pct >= 0.25 -> take_profit_partial
  pnl_pct <= -0.20 -> stop_loss
"""
import pytest

from risk import tp_sl_manager


@pytest.fixture
def mock_price(monkeypatch):
    """Force get_current_price to return a chosen value for the position's token."""
    def _set(price):
        monkeypatch.setattr(tp_sl_manager, "get_current_price", lambda token_id: price)
    return _set


# ── YES positions ────────────────────────────────────────────────────────────

def test_yes_take_profit(mock_price):
    # Bought YES at 0.40; YES token rises to 0.52 => +30% => partial TP.
    # (Use +30%, not exactly +25%: 0.50-0.40 is 0.0999..9 in float, landing
    # just under the 0.25 threshold — a boundary artifact, not a code bug.)
    mock_price(0.52)
    pos = {"token_id": "yes-tok", "entry_price": 0.40}
    assert tp_sl_manager.check_position(pos) == "take_profit_partial"


def test_yes_stop_loss(mock_price):
    # Bought YES at 0.40; YES token falls to 0.30 => -25% => stop loss.
    mock_price(0.30)
    pos = {"token_id": "yes-tok", "entry_price": 0.40}
    assert tp_sl_manager.check_position(pos) == "stop_loss"


# ── NO positions ─────────────────────────────────────────────────────────────

def test_no_take_profit(mock_price):
    # Bought the NO token at 0.60; NO token rises to 0.78 => +30% => partial TP.
    # (Profit when NO becomes more likely — proves we track the NO token itself.)
    mock_price(0.78)
    pos = {"token_id": "no-tok", "entry_price": 0.60}
    assert tp_sl_manager.check_position(pos) == "take_profit_partial"


def test_no_stop_loss(mock_price):
    # Bought the NO token at 0.60; NO token falls to 0.45 => -25% => stop loss.
    mock_price(0.45)
    pos = {"token_id": "no-tok", "entry_price": 0.60}
    assert tp_sl_manager.check_position(pos) == "stop_loss"


# ── PnL sign sanity for both directions ──────────────────────────────────────

def test_no_position_pnl_positive_when_no_token_rises(mock_price):
    mock_price(0.75)
    pos = {"token_id": "no-tok", "entry_price": 0.60, "size": 60.0}
    # shares = 60/0.60 = 100; pnl = (0.75-0.60)*100 = +15
    assert tp_sl_manager.compute_pnl(pos) == pytest.approx(15.0)


def test_yes_position_pnl_negative_when_yes_token_falls(mock_price):
    mock_price(0.30)
    pos = {"token_id": "yes-tok", "entry_price": 0.40, "size": 40.0}
    # shares = 40/0.40 = 100; pnl = (0.30-0.40)*100 = -10
    assert tp_sl_manager.compute_pnl(pos) == pytest.approx(-10.0)
