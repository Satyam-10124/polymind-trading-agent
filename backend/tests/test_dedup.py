"""
Persistent dedup state (db.models.dedup_*).

Replaces the old in-memory sets (seen_trade_ids, _consensus_processed,
_post_mortem_done). These tests pin the behavior that matters:
  - dedup survives a "restart" (data is in SQLite, not memory),
  - check-and-mark semantics are correct and idempotent,
  - the per-scope row cap evicts the OLDEST keys,
  - scopes are isolated from one another.

All tests use the temp_db fixture (fresh, migrated, isolated SQLite file).
"""
import db.models as models
from db.models import (
    dedup_contains, dedup_mark, dedup_seen, dedup_count,
)


def test_mark_then_contains(temp_db):
    assert dedup_contains("trade", "abc") is False
    dedup_mark("trade", "abc")
    assert dedup_contains("trade", "abc") is True


def test_mark_is_idempotent(temp_db):
    dedup_mark("trade", "abc")
    dedup_mark("trade", "abc")
    assert dedup_count("trade") == 1


def test_seen_check_and_mark(temp_db):
    # First sighting: not seen yet (returns False) but now recorded.
    assert dedup_seen("consensus", "mkt|YES") is False
    # Second sighting: already seen (returns True).
    assert dedup_seen("consensus", "mkt|YES") is True


def test_scopes_are_isolated(temp_db):
    dedup_mark("trade", "shared-key")
    assert dedup_contains("trade", "shared-key") is True
    # Same key string, different scope => independent.
    assert dedup_contains("post_mortem", "shared-key") is False


def test_none_key_is_safe(temp_db):
    # Guards monitor.py / jobs.py paths where an id may be missing.
    assert dedup_contains("trade", None) is False
    dedup_mark("trade", None)            # no-op, must not raise
    assert dedup_seen("trade", None) is False
    assert dedup_count("trade") == 0


def test_survives_restart(temp_db):
    """
    Simulate a process restart: mark a key, then re-run init_db (as startup does)
    and confirm the key is still there. The old in-memory sets failed this.
    """
    dedup_mark("seen_trade", "tx-123")
    assert dedup_contains("seen_trade", "tx-123") is True

    # "Restart": re-initialize the DB layer against the same file.
    models.init_db()

    assert dedup_contains("seen_trade", "tx-123") is True, \
        "dedup state must persist across restarts"


def test_size_cap_evicts_oldest(temp_db):
    """
    With a small cap, inserting more keys drops the OLDEST. created_at is an
    ISO timestamp; we pass increasing values implicitly by insertion order, and
    the (created_at DESC, rowid DESC) keep-set means the earliest inserts go.
    """
    cap = 5
    for i in range(10):
        dedup_mark("trade", f"key-{i:02d}", max_rows=cap)

    assert dedup_count("trade") == cap, "row count must be capped"
    # The 5 most-recent (key-05..key-09) survive; the oldest 5 are evicted.
    assert dedup_contains("trade", "key-09") is True
    assert dedup_contains("trade", "key-05") is True
    assert dedup_contains("trade", "key-04") is False
    assert dedup_contains("trade", "key-00") is False
