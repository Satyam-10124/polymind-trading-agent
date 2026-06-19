import logging

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from db.models import (
    init_db, get_stats, get_open_positions, get_all_positions,
    get_whale_profiles, get_committee_report, get_lessons, get_equity_curve,
    get_conn, get_backtest_runs, get_calibration_samples,
)
from executor.clob_client import get_wallet_balance
from config import PAPER_MODE, BANKROLL, API_TOKEN, DASHBOARD_ORIGINS

logger = logging.getLogger(__name__)

app = FastAPI(title="PolyMind API")

# CORS locked to the configured dashboard origin(s) — not "*". allow_credentials
# is on so a future cookie/session scheme works; with a wildcard origin browsers
# reject credentialed requests anyway, so an explicit list is required.
app.add_middleware(
    CORSMiddleware,
    allow_origins=DASHBOARD_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_token(authorization: str = Header(default="")):
    """
    Bearer-token gate for protected routes. If API_TOKEN is unset, auth is
    skipped (local dev). Otherwise the request must send
    `Authorization: Bearer <API_TOKEN>`.
    """
    if not API_TOKEN:
        return  # auth disabled — see startup warning
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


# Dependency list applied to every protected route (all except /api/status).
_AUTH = [Depends(require_token)]


@app.on_event("startup")
def startup():
    init_db()
    if not API_TOKEN:
        logger.warning(
            "API_TOKEN is not set — dashboard API auth is DISABLED. "
            "Set API_TOKEN in the environment for any non-local deployment."
        )
    logger.info(f"CORS allowed origins: {DASHBOARD_ORIGINS}")


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


@app.get("/api/positions", dependencies=_AUTH)
def positions(status: str = "open"):
    if status == "open":
        return get_open_positions()
    return get_all_positions(limit=100)


@app.get("/api/history", dependencies=_AUTH)
def history(limit: int = 50):
    return get_all_positions(limit=limit)


@app.get("/api/signals", dependencies=_AUTH)
def signals():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM signals ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/whales", dependencies=_AUTH)
def whales():
    """All profiled whale wallets with stats and per-category win rates."""
    return get_whale_profiles()


@app.get("/api/committee/{signal_id}", dependencies=_AUTH)
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


@app.get("/api/committee", dependencies=_AUTH)
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


@app.get("/api/lessons", dependencies=_AUTH)
def lessons(category: str = "all", limit: int = 100):
    """Post-mortem lessons, optionally filtered by event category."""
    return get_lessons(category=category, limit=limit)


@app.get("/api/equity", dependencies=_AUTH)
def equity():
    """Daily equity curve data points."""
    return get_equity_curve(starting_bankroll=BANKROLL)


@app.get("/api/consensus", dependencies=_AUTH)
def consensus(limit: int = 50):
    """Recent multi-whale consensus trigger events."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM consensus_events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/backtests", dependencies=_AUTH)
def backtests(limit: int = 20):
    """Saved backtest runs with train/test (out-of-sample) metrics."""
    return get_backtest_runs(limit=limit)


@app.get("/api/calibration", dependencies=_AUTH)
def calibration():
    """
    Reliability curve: predicted vs realized win frequency per probability bucket,
    plus the measured overconfidence factor. Answers 'do we trust our own prob?'
    """
    from risk.calibration import reliability_curve, overconfidence_factor
    samples = get_calibration_samples(limit=500)
    return {
        "n_samples": len(samples),
        "factor":    overconfidence_factor(samples),
        "curve":     reliability_curve(samples),
    }
