import json
import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "polymind.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS post_mortems (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        position_id     TEXT,
        question        TEXT,
        direction       TEXT,
        entry_price     REAL,
        exit_price      REAL,
        pnl             REAL,
        exit_reason     TEXT,
        edge_was_real   INTEGER,
        thesis_correct  INTEGER,
        lessons         TEXT,
        future_rules    TEXT,
        prompt_adjustments TEXT,
        created_at      TEXT
    );
    CREATE TABLE IF NOT EXISTS committee_reports (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        position_id     TEXT,
        question        TEXT,
        verdict         TEXT,
        conviction      INTEGER,
        whale_intent    TEXT,
        efficiency      TEXT,
        archetype       TEXT,
        cro             TEXT,
        portfolio       TEXT,
        sizing          TEXT,
        created_at      TEXT
    );
    """)
    conn.commit()
    conn.close()

    _init_positions_tables(conn)


def _init_positions_tables(conn):
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS positions (
        id          TEXT PRIMARY KEY,
        question    TEXT,
        market_id   TEXT,
        token_id    TEXT,
        direction   TEXT,
        entry_price REAL,
        size        REAL,
        shares      REAL,
        status      TEXT DEFAULT 'open',
        source      TEXT DEFAULT 'whale',
        whale_name  TEXT,
        claude_score INTEGER,
        reasoning   TEXT,
        opened_at   TEXT,
        closed_at   TEXT,
        exit_price  REAL,
        pnl         REAL DEFAULT 0,
        exit_reason TEXT
    );
    CREATE TABLE IF NOT EXISTS signals (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        question    TEXT,
        market_id   TEXT,
        direction   TEXT,
        score       INTEGER,
        edge        REAL,
        reasoning   TEXT,
        key_facts   TEXT,
        action      TEXT,
        created_at  TEXT
    );
    CREATE TABLE IF NOT EXISTS stats (
        date        TEXT PRIMARY KEY,
        start_bal   REAL,
        end_bal     REAL,
        daily_pnl   REAL,
        trades      INTEGER,
        wins        INTEGER,
        losses      INTEGER
    );
    """)
    conn.commit()
    conn.close()


def save_position(pos: dict):
    conn = get_conn()
    conn.execute("""
    INSERT OR REPLACE INTO positions
    (id, question, market_id, token_id, direction, entry_price, size, shares,
     status, source, whale_name, claude_score, reasoning, opened_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        pos["id"], pos.get("question"), pos.get("market_id"), pos.get("token_id"),
        pos.get("direction"), pos.get("entry_price"), pos.get("size"), pos.get("shares"),
        "open", pos.get("source", "whale"), pos.get("whale_name"),
        pos.get("claude_score"), pos.get("reasoning"),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


def close_position(pos_id: str, exit_price: float, pnl: float, reason: str):
    conn = get_conn()
    conn.execute("""
    UPDATE positions SET status='closed', exit_price=?, pnl=?,
    exit_reason=?, closed_at=? WHERE id=?
    """, (exit_price, pnl, reason, datetime.now(timezone.utc).isoformat(), pos_id))
    conn.commit()
    conn.close()


def get_open_positions() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM positions WHERE status='open'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_positions(limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM positions ORDER BY opened_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_signal(sig: dict):
    conn = get_conn()
    conn.execute("""
    INSERT INTO signals (question, market_id, direction, score, edge, reasoning,
                         key_facts, action, created_at)
    VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        sig.get("question"), sig.get("market_id"), sig.get("direction"),
        sig.get("score"), sig.get("edge"), sig.get("reasoning"),
        json.dumps(sig.get("key_facts", [])), sig.get("action", "skip"),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


def save_post_mortem(position: dict, report: dict):
    conn = get_conn()
    conn.execute("""
    INSERT INTO post_mortems
    (position_id, question, direction, entry_price, exit_price, pnl, exit_reason,
     edge_was_real, thesis_correct, lessons, future_rules, prompt_adjustments, created_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        position.get("id"), position.get("question"), position.get("direction"),
        position.get("entry_price"), position.get("exit_price"), position.get("pnl"),
        position.get("exit_reason"),
        int(report.get("edge_was_real", False)),
        int(report.get("thesis_correct", False)),
        json.dumps(report.get("lessons", [])),
        json.dumps(report.get("future_rules", [])),
        report.get("prompt_adjustments", ""),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


def save_committee_report(position_id: str, question: str, verdict: dict):
    import json as _json
    reports = verdict.get("committee_reports", {})
    conn = get_conn()
    conn.execute("""
    INSERT INTO committee_reports
    (position_id, question, verdict, conviction, whale_intent, efficiency,
     archetype, cro, portfolio, sizing, created_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        position_id, question,
        verdict.get("verdict"), verdict.get("conviction"),
        _json.dumps(reports.get("whale_intent", {})),
        _json.dumps(reports.get("efficiency", {})),
        _json.dumps(reports.get("archetype", {})),
        _json.dumps(reports.get("cro", {})),
        _json.dumps(reports.get("portfolio", {})),
        _json.dumps(reports.get("sizing", {})),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


def get_post_mortems(limit: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM post_mortems ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) as c FROM positions").fetchone()["c"]
    wins  = conn.execute("SELECT COUNT(*) as c FROM positions WHERE pnl > 0").fetchone()["c"]
    losses = conn.execute("SELECT COUNT(*) as c FROM positions WHERE pnl < 0 AND status='closed'").fetchone()["c"]
    total_pnl = conn.execute("SELECT COALESCE(SUM(pnl),0) as s FROM positions").fetchone()["s"]
    open_count = conn.execute("SELECT COUNT(*) as c FROM positions WHERE status='open'").fetchone()["c"]
    conn.close()
    win_rate = (wins / max(wins + losses, 1)) * 100
    return {
        "total_trades": total,
        "open_positions": open_count,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
    }
