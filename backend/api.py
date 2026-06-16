from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.models import (
    init_db, get_stats, get_open_positions, get_all_positions,
    get_whale_profiles, get_committee_report, get_lessons, get_equity_curve,
    get_conn,
)
from executor.clob_client import get_wallet_balance
from config import PAPER_MODE, BANKROLL

app = FastAPI(title="PolyMind API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/status")
def status():
    stats   = get_stats()
    balance = get_wallet_balance()
    return {
        "paper_mode":      PAPER_MODE,
        "wallet_balance":  balance,
        "total_pnl":       stats["total_pnl"],
        "win_rate":        stats["win_rate"],
        "total_trades":    stats["total_trades"],
        "open_positions":  stats["open_positions"],
        "wins":            stats["wins"],
        "losses":          stats["losses"],
    }


@app.get("/api/positions")
def positions(status: str = "open"):
    if status == "open":
        return get_open_positions()
    return get_all_positions(limit=100)


@app.get("/api/history")
def history(limit: int = 50):
    return get_all_positions(limit=limit)


@app.get("/api/signals")
def signals():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM signals ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/whales")
def whales():
    """All profiled whale wallets with stats and per-category win rates."""
    return get_whale_profiles()


@app.get("/api/committee/{signal_id}")
def committee(signal_id: str):
    """
    Full committee report for a position/signal. `signal_id` may be a position
    id (preferred) or a numeric signal id (resolved to its position_id).
    """
    report = get_committee_report(signal_id)
    if report is None and signal_id.isdigit():
        conn = get_conn()
        row = conn.execute(
            "SELECT position_id FROM signals WHERE id=?", (int(signal_id),)
        ).fetchone()
        conn.close()
        if row and row["position_id"]:
            report = get_committee_report(row["position_id"])
    if report is None:
        return {"error": "not found", "signal_id": signal_id}
    return report


@app.get("/api/committee")
def committee_list(limit: int = 50):
    """All committee reports (for the heatmap page)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM committee_reports ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    import json as _json
    out = []
    for r in rows:
        d = dict(r)
        for k in ("whale_intent", "efficiency", "archetype", "cro", "portfolio", "sizing"):
            try:
                d[k] = _json.loads(d.get(k) or "{}")
            except Exception:
                d[k] = {}
        out.append(d)
    return out


@app.get("/api/lessons")
def lessons(category: str = "all", limit: int = 100):
    """Post-mortem lessons, optionally filtered by event category."""
    return get_lessons(category=category, limit=limit)


@app.get("/api/equity")
def equity():
    """Daily equity curve data points."""
    return get_equity_curve(starting_bankroll=BANKROLL)


@app.get("/api/consensus")
def consensus(limit: int = 50):
    """Recent multi-whale consensus trigger events."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM consensus_events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
