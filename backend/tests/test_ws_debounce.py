"""
LiveFeed per-token WS debounce.

A busy market can print many trades per second; without debounce each print
fired a blocking, rate-limited /activity scan. _should_dispatch gates dispatch to
at most once per token per debounce window, and _extract_tokens pulls token ids
from a batch of WS events.

These exercise the pure helpers directly (no socket, no asyncio) with an explicit
clock so the timing is deterministic.
"""
from feed.live_feed import LiveFeed


def _feed(debounce=5.0):
    # Callback is never invoked by the pure helpers under test.
    return LiveFeed(on_consensus_trade=lambda trade: None, debounce_secs=debounce)


def test_first_print_dispatches():
    f = _feed()
    assert f._should_dispatch({"tokA"}, now=1000.0) is True


def test_second_print_within_window_suppressed():
    f = _feed(debounce=5.0)
    assert f._should_dispatch({"tokA"}, now=1000.0) is True
    # 2s later — inside the 5s window — must NOT dispatch.
    assert f._should_dispatch({"tokA"}, now=1002.0) is False


def test_dispatch_again_after_window():
    f = _feed(debounce=5.0)
    assert f._should_dispatch({"tokA"}, now=1000.0) is True
    assert f._should_dispatch({"tokA"}, now=1005.0) is True  # exactly at boundary


def test_window_is_per_token():
    f = _feed(debounce=5.0)
    assert f._should_dispatch({"tokA"}, now=1000.0) is True
    # A different token is independent — fires even though tokA is cooling down.
    assert f._should_dispatch({"tokB"}, now=1001.0) is True
    # tokA still suppressed at t=1001.
    assert f._should_dispatch({"tokA"}, now=1001.0) is False


def test_batch_fires_if_any_token_is_ready():
    f = _feed(debounce=5.0)
    f._should_dispatch({"tokA"}, now=1000.0)            # tokA marked
    # Batch with a cooling tokA + a fresh tokC => should fire (tokC is ready).
    assert f._should_dispatch({"tokA", "tokC"}, now=1001.0) is True


def test_no_tokens_falls_back_to_global_debounce():
    f = _feed(debounce=5.0)
    # Prints without token ids still rate-limit via a single global key.
    assert f._should_dispatch(set(), now=1000.0) is True
    assert f._should_dispatch(set(), now=1002.0) is False
    assert f._should_dispatch(set(), now=1006.0) is True


def test_extract_tokens_reads_common_fields():
    events = [
        {"event_type": "trade", "asset_id": "111"},
        {"type": "trade", "asset": "222"},
        {"event_type": "last_trade_price", "market": "333"},
        {"event_type": "trade"},          # no token — ignored
        "garbage",                          # non-dict — ignored
    ]
    assert LiveFeed._extract_tokens(events) == {"111", "222", "333"}
