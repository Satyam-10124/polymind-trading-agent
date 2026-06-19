"""
filter_whales_by_recency — drop whales with negative trailing-window PnL.

A trader top-ranked by ALL-TIME PnL may have blown up recently. We fetch each
candidate's /activity, sum PnL within WHALE_RECENCY_DAYS, and drop anyone
negative. Fetches are cached aggressively per wallet. On a fetch failure we
fail-open (keep the whale) so a transient API error can't empty the whale set.

get_whale_activity is stubbed so these tests never hit the network.
"""
import pytest

import whale.monitor as monitor

NOW = 1_700_000_000.0  # fixed clock so window math is deterministic


@pytest.fixture(autouse=True)
def clear_cache():
    monitor._recency_cache.clear()
    yield
    monitor._recency_cache.clear()


def _stub_activity(mapping, monkeypatch, counter=None):
    def fake(wallet, limit=200):
        if counter is not None:
            counter[wallet] = counter.get(wallet, 0) + 1
        return mapping.get(wallet, [])
    monkeypatch.setattr(monitor, "get_whale_activity", fake)


def _whale(name):
    return {"proxyWallet": name, "userName": name}


def test_positive_recent_pnl_kept(monkeypatch):
    _stub_activity({"good": [{"timestamp": NOW - 5 * 86400, "pnl": 1000}]}, monkeypatch)
    out = monitor.filter_whales_by_recency([_whale("good")], now=NOW)
    assert [w["userName"] for w in out] == ["good"]
    assert out[0]["recent_pnl"] == 1000.0


def test_negative_recent_pnl_dropped(monkeypatch):
    _stub_activity({"bad": [{"timestamp": NOW - 5 * 86400, "pnl": -1500}]}, monkeypatch)
    out = monitor.filter_whales_by_recency([_whale("bad")], now=NOW)
    assert out == []


def test_old_losses_excluded_from_window(monkeypatch):
    # A huge loss OUTSIDE the 90d window must not count; recent net is positive.
    _stub_activity({"recovered": [
        {"timestamp": NOW - 200 * 86400, "pnl": -50_000},  # old, excluded
        {"timestamp": NOW - 10 * 86400, "pnl": 800},       # recent, counts
    ]}, monkeypatch)
    out = monitor.filter_whales_by_recency([_whale("recovered")], now=NOW)
    assert [w["userName"] for w in out] == ["recovered"]
    assert out[0]["recent_pnl"] == 800.0


def test_fetch_failure_fails_open(monkeypatch):
    # Empty activity => recent_pnl returns None => whale is KEPT.
    _stub_activity({}, monkeypatch)
    out = monitor.filter_whales_by_recency([_whale("mystery")], now=NOW)
    assert [w["userName"] for w in out] == ["mystery"]
    assert "recent_pnl" not in out[0]  # not set when we couldn't measure


def test_results_are_cached(monkeypatch):
    counter = {}
    _stub_activity({"w": [{"timestamp": NOW - 1 * 86400, "pnl": 10}]}, monkeypatch, counter)
    monitor.filter_whales_by_recency([_whale("w")], now=NOW)
    monitor.filter_whales_by_recency([_whale("w")], now=NOW + 60)  # within TTL
    assert counter["w"] == 1, "second call within TTL must hit cache, not refetch"


def test_cache_expires(monkeypatch):
    from config import WHALE_RECENCY_CACHE_SECS
    counter = {}
    _stub_activity({"w": [{"timestamp": NOW - 1 * 86400, "pnl": 10}]}, monkeypatch, counter)
    monitor.filter_whales_by_recency([_whale("w")], now=NOW)
    monitor.filter_whales_by_recency([_whale("w")], now=NOW + WHALE_RECENCY_CACHE_SECS + 1)
    assert counter["w"] == 2, "after TTL expiry the wallet must be refetched"


def test_mixed_set(monkeypatch):
    _stub_activity({
        "keep": [{"timestamp": NOW - 3 * 86400, "pnl": 200}],
        "drop": [{"timestamp": NOW - 3 * 86400, "pnl": -200}],
    }, monkeypatch)
    out = monitor.filter_whales_by_recency([_whale("keep"), _whale("drop")], now=NOW)
    assert [w["userName"] for w in out] == ["keep"]
