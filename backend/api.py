from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.models import init_db, get_stats, get_open_positions, get_all_positions
from executor.clob_client import get_wallet_balance
from config import PAPER_MODE

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
    import sqlite3
    from db.models import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM signals ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
