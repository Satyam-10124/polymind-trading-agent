"""
normalize_ts — epoch timestamps from the data-api come in seconds OR
milliseconds; everything downstream assumes seconds. The helper auto-detects
(>1e12 => ms) so the freshness filter and age math don't silently break.
"""
import time

import pytest

from whale.monitor import normalize_ts, is_trade_fresh


# A recent, realistic instant in both units.
_SECONDS = 1_700_000_000          # ~Nov 2023, epoch seconds (~1.7e9)
_MILLIS = 1_700_000_000_000       # same instant in milliseconds (~1.7e12)


def test_seconds_passthrough():
    assert normalize_ts(_SECONDS) == float(_SECONDS)


def test_milliseconds_divided():
    assert normalize_ts(_MILLIS) == float(_SECONDS)


def test_seconds_and_millis_agree():
    assert normalize_ts(_SECONDS) == normalize_ts(_MILLIS)


def test_float_millis():
    assert normalize_ts(1_700_000_000_000.0) == pytest.approx(_SECONDS)


def test_numeric_string_accepted():
    # The data-api sometimes sends epochs as strings.
    assert normalize_ts("1700000000000") == float(_SECONDS)


def test_non_numeric_returns_none():
    assert normalize_ts(None) is None
    assert normalize_ts("not-a-number") is None


def test_boundary_just_under_1e12_is_seconds():
    # 1e12 - 1 must NOT be divided (still treated as seconds).
    assert normalize_ts(1e12 - 1) == 1e12 - 1


# ── End-to-end: freshness filter must work for ms timestamps ──────────────────

def test_is_trade_fresh_handles_millisecond_timestamp():
    now_ms = time.time() * 1000.0          # fresh, in milliseconds
    assert is_trade_fresh({"timestamp": now_ms}) is True


def test_is_trade_fresh_stale_millisecond_timestamp():
    old_ms = (time.time() - 10_000) * 1000.0   # ~2.8h old, well past the window
    assert is_trade_fresh({"timestamp": old_ms}) is False


def test_is_trade_fresh_fresh_seconds_still_work():
    assert is_trade_fresh({"timestamp": time.time()}) is True
