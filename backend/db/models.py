import json
import sqlite3
import os
from datetime import datetime, timezone

# Defaults to backend/../polymind.db for local dev. In production set DB_PATH to
# a file on a persistent disk (e.g. Render mounts one at /data) so SQLite state
# survives restarts and redeploys.
DB_PATH = os.getenv("DB_PATH") or os.path.join(os.path.dirname(__file__), "..", "polymind.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Tune every connection for concurrent writers (scheduler + telegram +
    # FastAPI all open their own connections per call):
    #   WAL          — readers don't block writers and vice versa.
    #   NORMAL       — durable under WAL, far cheaper than FULL fsync-per-commit.
    #   busy_timeout — wait up to 5s for a lock instead of erroring immediately.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
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
    CREATE TABLE IF NOT EXISTS whale_profiles (
        wallet            TEXT PRIMARY KEY,
        username          TEXT,
        pnl               REAL,
        avg_bet_size      REAL,
        top_categories    TEXT,
        win_rate          REAL,
        total_trades      INTEGER,
        recent_streak     TEXT,
        category_win_rates TEXT,
        avg_hold_hours    REAL,
        closes_early      INTEGER,
        hold_to_resolution_pct REAL,
        conviction_signal TEXT,
        avg_tranches      REAL,
        updated_at        TEXT
    );
    CREATE TABLE IF NOT EXISTS lessons_learned (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        position_id     TEXT,
        category        TEXT,
        lesson          TEXT,
        future_rule     TEXT,
        pnl             REAL,
        edge_was_real   INTEGER,
        thesis_correct  INTEGER,
        applied_count   INTEGER DEFAULT 0,
        reduced_losses  INTEGER DEFAULT 0,
        ignored         INTEGER DEFAULT 0,
        created_at      TEXT
    );
    CREATE TABLE IF NOT EXISTS sizing_decisions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        position_id     TEXT,
        question        TEXT,
        bankroll        REAL,
        my_prob         REAL,
        market_price    REAL,
        edge            REAL,
        raw_kelly       REAL,
        recent_win_rate REAL,
        kelly_fraction  REAL,
        drawdown_pct    REAL,
        circuit_breaker INTEGER DEFAULT 0,
        final_bet       REAL,
        breakdown       TEXT,
        created_at      TEXT
    );
    CREATE TABLE IF NOT EXISTS consensus_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        market_id       TEXT,
        question        TEXT,
        direction       TEXT,
        whale_count     INTEGER,
        consensus_score REAL,
        whales          TEXT,
        created_at      TEXT
    );
    -- ── Backtest / historical data ────────────────────────────
    -- Raw whale trades pulled from the data-api, used to replay the strategy.
    CREATE TABLE IF NOT EXISTS historical_trades (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id      TEXT UNIQUE,
        wallet        TEXT,
        username      TEXT,
        whale_pnl     REAL,
        market_id     TEXT,
        token_id      TEXT,
        question      TEXT,
        category      TEXT,
        direction     TEXT,
        price         REAL,
        size          REAL,
        ts            REAL,
        created_at    TEXT
    );
    -- Price time-series per token (from Gamma prices-history).
    CREATE TABLE IF NOT EXISTS market_prices (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        token_id      TEXT,
        market_id     TEXT,
        ts            REAL,
        price         REAL,
        UNIQUE(token_id, ts)
    );
    -- Final resolution per market for outcome scoring.
    CREATE TABLE IF NOT EXISTS market_resolutions (
        market_id     TEXT PRIMARY KEY,
        question      TEXT,
        resolved_outcome TEXT,
        resolved_price   REAL,
        resolved_ts      REAL,
        created_at    TEXT
    );
    -- One row per backtest run with summary metrics + JSON config/results.
    CREATE TABLE IF NOT EXISTS backtest_runs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        label         TEXT,
        train_start   TEXT,
        train_end     TEXT,
        test_start    TEXT,
        test_end      TEXT,
        n_trades      INTEGER,
        win_rate      REAL,
        total_pnl     REAL,
        roi           REAL,
        sharpe        REAL,
        max_drawdown  REAL,
        avg_slippage  REAL,
        config        TEXT,
        results       TEXT,
        created_at    TEXT
    );
    -- ── Dedup state ───────────────────────────────────────────
    -- Persistent replacement for the old in-memory dedup sets (seen trade ids,
    -- processed consensus keys, completed post-mortems). `scope` namespaces the
    -- key kind so one table serves all callers; (scope, key) is unique. Bounded
    -- by a hard row cap (oldest dropped) so it can never grow without limit.
    CREATE TABLE IF NOT EXISTS dedup_keys (
        scope       TEXT NOT NULL,
        key         TEXT NOT NULL,
        created_at  TEXT,
        PRIMARY KEY (scope, key)
    );
    CREATE INDEX IF NOT EXISTS idx_dedup_scope_created
        ON dedup_keys (scope, created_at);
    """)
    conn.commit()
    conn.close()

    _init_positions_tables(conn)
    _run_migrations()


def _safe_add_column(table: str, column: str, decl: str):
    conn = get_conn()
    try:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _safe_exec(sql: str):
    """Run a single idempotent DDL statement, swallowing 'already exists'."""
    conn = get_conn()
    try:
        conn.execute(sql)
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _run_migrations():
    # Columns added after initial release — safe to run repeatedly.
    _safe_add_column("positions", "category", "TEXT")
    _safe_add_column("positions", "consensus_score", "REAL DEFAULT 0")
    _safe_add_column("positions", "resolve_date", "TEXT")
    _safe_add_column("positions", "event_key", "TEXT")
    # Marks that the first take-profit tier already sold its slice, so the
    # remainder isn't re-sold on every subsequent position check.
    _safe_add_column("positions", "partial_tp_done", "INTEGER DEFAULT 0")
    _safe_add_column("signals", "consensus_score", "REAL DEFAULT 0")
    _safe_add_column("signals", "position_id", "TEXT")
    # Persistent dedup state (replaces in-memory sets). Created here too so
    # existing deployments that predate the table are migrated in place.
    _safe_exec("""
        CREATE TABLE IF NOT EXISTS dedup_keys (
            scope       TEXT NOT NULL,
            key         TEXT NOT NULL,
            created_at  TEXT,
            PRIMARY KEY (scope, key)
        )
    """)
    _safe_exec("CREATE INDEX IF NOT EXISTS idx_dedup_scope_created ON dedup_keys (scope, created_at)")


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
     status, source, whale_name, claude_score, reasoning, category, consensus_score,
     resolve_date, event_key, opened_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        pos["id"], pos.get("question"), pos.get("market_id"), pos.get("token_id"),
        pos.get("direction"), pos.get("entry_price"), pos.get("size"), pos.get("shares"),
        "open", pos.get("source", "whale"), pos.get("whale_name"),
        pos.get("claude_score"), pos.get("reasoning"),
        pos.get("category", "other"), pos.get("consensus_score", 0),
        pos.get("resolve_date"), pos.get("event_key"),
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


def update_position(pos_id: str, shares: float, size: float,
                    partial_tp_done: bool | None = None):
    """
    Persist a reduced share/size count after a partial exit (and optionally flip
    the partial_tp_done flag). Without this, get_open_positions() reloads the
    original full share count from SQLite and the partial sell re-triggers.
    """
    if partial_tp_done is None:
        conn = get_conn()
        conn.execute(
            "UPDATE positions SET shares=?, size=? WHERE id=?",
            (shares, size, pos_id),
        )
    else:
        conn = get_conn()
        conn.execute(
            "UPDATE positions SET shares=?, size=?, partial_tp_done=? WHERE id=?",
            (shares, size, 1 if partial_tp_done else 0, pos_id),
        )
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
                         key_facts, action, consensus_score, position_id, created_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        sig.get("question"), sig.get("market_id"), sig.get("direction"),
        sig.get("score"), sig.get("edge"), sig.get("reasoning"),
        json.dumps(sig.get("key_facts", [])), sig.get("action", "skip"),
        sig.get("consensus_score", 0), sig.get("position_id"),
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


# ── Whale profiles ────────────────────────────────────────────

def save_whale_profile(profile: dict):
    conn = get_conn()
    conn.execute("""
    INSERT OR REPLACE INTO whale_profiles
    (wallet, username, pnl, avg_bet_size, top_categories, win_rate, total_trades,
     recent_streak, category_win_rates, avg_hold_hours, closes_early,
     hold_to_resolution_pct, conviction_signal, avg_tranches, updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        profile.get("wallet"), profile.get("username"), profile.get("pnl", 0),
        profile.get("avg_bet_size", 0),
        json.dumps(profile.get("top_categories", [])),
        profile.get("win_rate", 0), profile.get("total_trades", 0),
        profile.get("recent_streak", ""),
        json.dumps(profile.get("category_win_rates", {})),
        profile.get("avg_hold_hours", 0),
        int(profile.get("closes_early", False)),
        profile.get("hold_to_resolution_pct", 0),
        profile.get("conviction_signal", "unknown"),
        profile.get("avg_tranches", 1),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


def get_whale_profiles() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM whale_profiles ORDER BY pnl DESC"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("top_categories", "category_win_rates"):
            try:
                d[k] = json.loads(d.get(k) or ("[]" if k == "top_categories" else "{}"))
            except Exception:
                d[k] = [] if k == "top_categories" else {}
        out.append(d)
    return out


# ── Lessons learned ───────────────────────────────────────────

def save_lessons(position: dict, report: dict):
    """Explode a post-mortem report into individual lesson rows."""
    conn = get_conn()
    category = position.get("category", "other")
    pnl      = float(position.get("pnl", 0))
    edge     = int(report.get("edge_was_real", False))
    thesis   = int(report.get("thesis_correct", False))
    rules    = report.get("future_rules", []) or [""]
    for i, lesson in enumerate(report.get("lessons", [])):
        rule = rules[i] if i < len(rules) else (rules[0] if rules else "")
        conn.execute("""
        INSERT INTO lessons_learned
        (position_id, category, lesson, future_rule, pnl, edge_was_real,
         thesis_correct, created_at)
        VALUES (?,?,?,?,?,?,?,?)
        """, (
            position.get("id"), category, lesson, rule, pnl, edge, thesis,
            datetime.now(timezone.utc).isoformat(),
        ))
    conn.commit()
    conn.close()


def get_lessons(category: str | None = None, limit: int = 50) -> list[dict]:
    conn = get_conn()
    if category and category != "all":
        rows = conn.execute(
            "SELECT * FROM lessons_learned WHERE category=? ORDER BY created_at DESC LIMIT ?",
            (category, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM lessons_learned ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_lessons_for_category(category: str, limit: int = 5) -> list[dict]:
    """Used to inject prior lessons into committee prompts before analysis."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM lessons_learned WHERE category=? ORDER BY created_at DESC LIMIT ?",
        (category, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_lessons_applied(category: str, helped: bool):
    """Track whether injected lessons reduced losses (helped) or were ignored."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id FROM lessons_learned WHERE category=? ORDER BY created_at DESC LIMIT 5",
        (category,),
    ).fetchall()
    for r in rows:
        if helped:
            conn.execute(
                "UPDATE lessons_learned SET applied_count=applied_count+1, "
                "reduced_losses=reduced_losses+1 WHERE id=?", (r["id"],))
        else:
            conn.execute(
                "UPDATE lessons_learned SET applied_count=applied_count+1, "
                "ignored=ignored+1 WHERE id=?", (r["id"],))
    conn.commit()
    conn.close()


# ── Sizing decisions ──────────────────────────────────────────

def save_sizing_decision(decision: dict):
    conn = get_conn()
    conn.execute("""
    INSERT INTO sizing_decisions
    (position_id, question, bankroll, my_prob, market_price, edge, raw_kelly,
     recent_win_rate, kelly_fraction, drawdown_pct, circuit_breaker, final_bet,
     breakdown, created_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        decision.get("position_id"), decision.get("question"),
        decision.get("bankroll"), decision.get("my_prob"),
        decision.get("market_price"), decision.get("edge"),
        decision.get("raw_kelly"), decision.get("recent_win_rate"),
        decision.get("kelly_fraction"), decision.get("drawdown_pct"),
        int(decision.get("circuit_breaker", False)), decision.get("final_bet"),
        json.dumps(decision.get("breakdown", {})),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


def get_recent_outcomes(limit: int = 20) -> list[int]:
    """Returns 1/0 win flags for the last N closed trades (most recent first)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT pnl FROM positions WHERE status='closed' ORDER BY closed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [1 if float(r["pnl"] or 0) > 0 else 0 for r in rows]


# ── Consensus events ──────────────────────────────────────────

def save_consensus_event(event: dict):
    conn = get_conn()
    conn.execute("""
    INSERT INTO consensus_events
    (market_id, question, direction, whale_count, consensus_score, whales, created_at)
    VALUES (?,?,?,?,?,?,?)
    """, (
        event.get("market_id"), event.get("question"), event.get("direction"),
        event.get("whale_count"), event.get("consensus_score"),
        json.dumps(event.get("whales", [])),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


# ── Committee report lookup ───────────────────────────────────

def get_committee_report(position_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM committee_reports WHERE position_id=? ORDER BY created_at DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("whale_intent", "efficiency", "archetype", "cro", "portfolio", "sizing"):
        try:
            d[k] = json.loads(d.get(k) or "{}")
        except Exception:
            d[k] = {}
    return d


# ── Equity curve ──────────────────────────────────────────────

def get_equity_curve(starting_bankroll: float = 50.0) -> list[dict]:
    """Daily cumulative equity points from closed-trade PnL."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT substr(closed_at, 1, 10) as day, COALESCE(SUM(pnl), 0) as day_pnl,
               COUNT(*) as trades
        FROM positions
        WHERE status='closed' AND closed_at IS NOT NULL
        GROUP BY day ORDER BY day ASC
    """).fetchall()
    conn.close()
    equity = starting_bankroll
    points = []
    for r in rows:
        equity += float(r["day_pnl"] or 0)
        points.append({
            "date":   r["day"],
            "pnl":    round(float(r["day_pnl"] or 0), 2),
            "equity": round(equity, 2),
            "trades": r["trades"],
        })
    return points


# ── Historical data (backtest) ────────────────────────────────

def save_historical_trades(trades: list[dict]) -> int:
    """Bulk-insert raw whale trades. Returns count of newly inserted rows."""
    conn = get_conn()
    n = 0
    for t in trades:
        try:
            cur = conn.execute("""
            INSERT OR IGNORE INTO historical_trades
            (trade_id, wallet, username, whale_pnl, market_id, token_id, question,
             category, direction, price, size, ts, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                t.get("trade_id"), t.get("wallet"), t.get("username"),
                t.get("whale_pnl", 0), t.get("market_id"), t.get("token_id"),
                t.get("question"), t.get("category", "other"), t.get("direction"),
                t.get("price"), t.get("size"), t.get("ts"),
                datetime.now(timezone.utc).isoformat(),
            ))
            n += cur.rowcount
        except Exception:
            pass
    conn.commit()
    conn.close()
    return n


def get_historical_trades(start_ts: float | None = None, end_ts: float | None = None) -> list[dict]:
    conn = get_conn()
    q = "SELECT * FROM historical_trades"
    params: list = []
    clauses = []
    if start_ts is not None:
        clauses.append("ts >= ?"); params.append(start_ts)
    if end_ts is not None:
        clauses.append("ts <= ?"); params.append(end_ts)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY ts ASC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_market_prices(token_id: str, market_id: str, points: list[dict]) -> int:
    conn = get_conn()
    n = 0
    for p in points:
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO market_prices (token_id, market_id, ts, price) VALUES (?,?,?,?)",
                (token_id, market_id, float(p["ts"]), float(p["price"])),
            )
            n += cur.rowcount
        except Exception:
            pass
    conn.commit()
    conn.close()
    return n


def get_price_at(token_id: str, ts: float) -> float | None:
    """Most recent recorded price for token at-or-before ts (point-in-time, no lookahead)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT price FROM market_prices WHERE token_id=? AND ts<=? ORDER BY ts DESC LIMIT 1",
        (token_id, ts),
    ).fetchone()
    conn.close()
    return float(row["price"]) if row else None


def save_market_resolution(res: dict):
    conn = get_conn()
    conn.execute("""
    INSERT OR REPLACE INTO market_resolutions
    (market_id, question, resolved_outcome, resolved_price, resolved_ts, created_at)
    VALUES (?,?,?,?,?,?)
    """, (
        res.get("market_id"), res.get("question"), res.get("resolved_outcome"),
        res.get("resolved_price"), res.get("resolved_ts"),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


def get_market_resolution(market_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM market_resolutions WHERE market_id=?", (market_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_backtest_run(run: dict) -> int:
    conn = get_conn()
    cur = conn.execute("""
    INSERT INTO backtest_runs
    (label, train_start, train_end, test_start, test_end, n_trades, win_rate,
     total_pnl, roi, sharpe, max_drawdown, avg_slippage, config, results, created_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        run.get("label"), run.get("train_start"), run.get("train_end"),
        run.get("test_start"), run.get("test_end"), run.get("n_trades"),
        run.get("win_rate"), run.get("total_pnl"), run.get("roi"),
        run.get("sharpe"), run.get("max_drawdown"), run.get("avg_slippage"),
        json.dumps(run.get("config", {})), json.dumps(run.get("results", {})),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def get_backtest_runs(limit: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("config", "results"):
            try:
                d[k] = json.loads(d.get(k) or "{}")
            except Exception:
                d[k] = {}
        out.append(d)
    return out


# ── Calibration ───────────────────────────────────────────────

def get_calibration_samples(limit: int = 500) -> list[dict]:
    """
    Pairs of (predicted probability, realized win) for closed positions.
    Predicted prob = the sizing_decisions.my_prob logged at entry; realized win
    = whether the position closed with pnl>0. Joined on position_id.
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT s.my_prob AS my_prob, p.pnl AS pnl, p.direction AS direction
        FROM sizing_decisions s
        JOIN positions p ON p.id = s.position_id
        WHERE p.status='closed' AND s.my_prob IS NOT NULL
        ORDER BY p.closed_at DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [
        {"my_prob": float(r["my_prob"]), "win": 1 if float(r["pnl"] or 0) > 0 else 0}
        for r in rows
    ]


# ── Persistent dedup state ────────────────────────────────────
# Replaces the old in-memory sets (seen_trade_ids, _consensus_processed,
# _post_mortem_done) so dedup survives restarts and can never grow unbounded.
# Each caller uses its own `scope` string; (scope, key) is unique. Per scope we
# keep at most DEDUP_MAX_ROWS rows, evicting the oldest on insert.

DEDUP_MAX_ROWS = 50_000


def dedup_contains(scope: str, key: str) -> bool:
    """True if (scope, key) has already been recorded."""
    if key is None:
        return False
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM dedup_keys WHERE scope=? AND key=? LIMIT 1", (scope, str(key))
    ).fetchone()
    conn.close()
    return row is not None


def dedup_mark(scope: str, key: str, max_rows: int = DEDUP_MAX_ROWS):
    """
    Record (scope, key). Idempotent (INSERT OR IGNORE). After inserting, enforce
    the per-scope row cap by deleting the oldest rows beyond `max_rows`.
    """
    if key is None:
        return
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO dedup_keys (scope, key, created_at) VALUES (?,?,?)",
            (scope, str(key), datetime.now(timezone.utc).isoformat()),
        )
        # Evict oldest rows in this scope beyond the cap. rowid is monotonic with
        # insertion, so it's a stable tiebreaker when created_at collides.
        conn.execute(
            """
            DELETE FROM dedup_keys
            WHERE scope=? AND rowid NOT IN (
                SELECT rowid FROM dedup_keys WHERE scope=?
                ORDER BY created_at DESC, rowid DESC LIMIT ?
            )
            """,
            (scope, scope, max_rows),
        )
        conn.commit()
    finally:
        conn.close()


def dedup_seen(scope: str, key: str, max_rows: int = DEDUP_MAX_ROWS) -> bool:
    """
    Check-and-mark in one call. Returns True if the key was ALREADY present
    (caller should skip), False if it was newly recorded (caller should proceed).
    """
    if key is None:
        return False
    if dedup_contains(scope, key):
        return True
    dedup_mark(scope, key, max_rows=max_rows)
    return False


def dedup_count(scope: str) -> int:
    """Number of recorded keys in a scope (for tests / introspection)."""
    conn = get_conn()
    n = conn.execute(
        "SELECT COUNT(*) AS c FROM dedup_keys WHERE scope=?", (scope,)
    ).fetchone()["c"]
    conn.close()
    return n
