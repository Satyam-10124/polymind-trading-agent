"""
WAL mode + concurrent-writer settings on every connection (db.models.get_conn).

The bot opens a fresh connection per call from three threads (scheduler,
telegram, FastAPI), so connections must tolerate concurrent writers. These tests
confirm get_conn sets WAL / NORMAL / busy_timeout, and that two independent
connections can each write without the second erroring or blocking.
"""
import db.models as models
from db.models import get_conn


def test_pragmas_set_on_every_connection(temp_db):
    conn = get_conn()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_two_connections_write_without_blocking(temp_db):
    """
    Open two connections and write from each. Under WAL with a busy_timeout,
    the second writer must not raise 'database is locked'. We interleave: open
    both, write+commit on each, and confirm both rows persisted.
    """
    a = get_conn()
    b = get_conn()
    try:
        a.execute(
            "INSERT INTO dedup_keys (scope, key, created_at) VALUES (?,?,?)",
            ("conn_a", "k1", "2026-01-01T00:00:00Z"),
        )
        a.commit()

        # Second connection writes while the first is still open.
        b.execute(
            "INSERT INTO dedup_keys (scope, key, created_at) VALUES (?,?,?)",
            ("conn_b", "k2", "2026-01-01T00:00:01Z"),
        )
        b.commit()

        # A third connection sees both committed rows.
        c = get_conn()
        try:
            n = c.execute("SELECT COUNT(*) AS c FROM dedup_keys").fetchone()["c"]
        finally:
            c.close()
        assert n == 2, f"expected both writes to persist, found {n}"
    finally:
        a.close()
        b.close()


def test_concurrent_threads_write(temp_db):
    """
    Stronger check: many threads each open their own connection and write,
    mirroring scheduler + telegram + FastAPI hitting the DB at once. With WAL +
    busy_timeout this completes without 'database is locked'.
    """
    import threading

    errors = []

    def worker(i):
        try:
            conn = get_conn()
            conn.execute(
                "INSERT INTO dedup_keys (scope, key, created_at) VALUES (?,?,?)",
                ("threaded", f"key-{i}", "2026-01-01T00:00:00Z"),
            )
            conn.commit()
            conn.close()
        except Exception as e:  # noqa: BLE001 — surface any lock error
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent writers raised: {errors[:3]}"
    n = models.dedup_count("threaded")
    assert n == 20, f"expected 20 rows, found {n}"
