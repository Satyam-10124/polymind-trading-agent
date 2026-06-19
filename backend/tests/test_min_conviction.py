"""
MIN_CLAUDE_SCORE enforcement in scheduler.jobs.process_whale_trade.

A committee APPROVE whose conviction is below MIN_CLAUDE_SCORE must be downgraded
to WATCH and must NOT place an order. A high-conviction APPROVE must still trade
(positive control, so the no-order assertion isn't vacuous).

We stub the network/committee boundaries and drive a synthetic verdict through
the real gate. DB writes that run before the gate use the temp_db fixture.
"""
import time

import pytest
import requests

import scheduler.jobs as jobs


class _FakeResp:
    ok = True

    def json(self):
        return [{
            "conditionId": "mkt-conv-test",
            "clobTokenIds": ["tokYES", "tokNO"],
            "question": "Will it resolve YES?",
            "category": "politics",
            "endDate": "2027-01-01T00:00:00Z",
        }]


@pytest.fixture
def harness(monkeypatch, temp_db):
    """Stub every boundary process_whale_trade touches and spy on place_order."""
    # Consensus dedup now lives in the dedup_keys table; the temp_db fixture
    # gives each test a fresh empty DB, so no manual reset is needed.
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResp())
    monkeypatch.setattr(jobs, "get_current_price", lambda token_id: 0.5)
    monkeypatch.setattr(jobs, "compute_consensus", lambda market_id, side: {
        "aligned": True, "whale_count": 3, "consensus_score": 0.8,
        "whales": [{"username": "w1", "pnl": 1_000_000}],
    })
    monkeypatch.setattr(jobs, "build_profile", lambda *a, **k: {})
    monkeypatch.setattr(jobs, "save_whale_profile", lambda *a, **k: None)

    placed = []
    monkeypatch.setattr(jobs, "place_order",
                        lambda *a, **k: placed.append((a, k)) or {"status": "paper"})

    notes = []
    monkeypatch.setattr(jobs, "notify", lambda msg: notes.append(msg))

    def _verdict(conviction):
        return {
            "verdict": "APPROVE", "conviction": conviction, "direction": "YES",
            "capital_allocation": 5.0, "my_probability": 0.6,
            "reasoning": "test thesis", "committee_reports": {"cro": {}},
        }

    return {"placed": placed, "notes": notes, "set_verdict": _verdict, "monkeypatch": monkeypatch}


def _trade():
    return {"conditionId": "mkt-conv-test", "title": "Will it resolve YES?",
            "side": "YES", "timestamp": time.time(), "whale_username": "w1"}


def test_low_conviction_approve_places_no_order(harness):
    # Conviction 3 < MIN_CLAUDE_SCORE (7) → must downgrade to WATCH, no order.
    harness["monkeypatch"].setattr(jobs, "run_committee",
                                   lambda **kw: harness["set_verdict"](3))

    jobs.process_whale_trade(_trade(), open_pos=[], bankroll=1000.0)

    assert harness["placed"] == [], "low-conviction APPROVE must not place an order"
    assert any("WATCH" in n and "conviction" in n.lower() for n in harness["notes"]), \
        "expected a downgrade notification mentioning WATCH + conviction"


def test_high_conviction_approve_places_order(harness):
    # Conviction 9 >= 7 → trades normally (positive control).
    harness["monkeypatch"].setattr(jobs, "run_committee",
                                   lambda **kw: harness["set_verdict"](9))

    jobs.process_whale_trade(_trade(), open_pos=[], bankroll=1000.0)

    assert len(harness["placed"]) == 1, "high-conviction APPROVE should place exactly one order"
