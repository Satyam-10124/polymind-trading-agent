"""
Historical data ingestion from Polymarket public APIs.

Pulls, for the current whale set:
  - each whale's trade history (data-api /activity)        -> historical_trades
  - per-token price time-series (gamma /prices-history)    -> market_prices
  - final market resolution (gamma /markets)               -> market_resolutions

Run:  python3 -m backtest.ingest [--whales N] [--days D]

This is intentionally idempotent (INSERT OR IGNORE) so it can be re-run to extend
the dataset. No credentials required — all endpoints are public reads.
"""
import sys
import time
import logging
import argparse
import requests
from datetime import datetime, timezone

from config import DATA_API, GAMMA_API
from whale.monitor import get_leaderboard, filter_whales
from whale.profiler import _bucket_category
from db.models import (
    init_db, save_historical_trades, save_market_prices, save_market_resolution,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest")


def _ts(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def fetch_wallet_trades(wallet: str, username: str, whale_pnl: float, limit: int = 500) -> list[dict]:
    try:
        r = requests.get(f"{DATA_API}/activity", params={"user": wallet, "limit": limit}, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"activity fetch {wallet[:8]}: {e}")
        return []
    if not isinstance(data, list):
        return []

    out = []
    for t in data:
        ts = _ts(t.get("timestamp") or t.get("createdAt") or t.get("time"))
        if ts is None:
            continue
        market_id = t.get("conditionId") or t.get("market", {}).get("conditionId") or t.get("slug")
        if not market_id:
            continue
        question = t.get("title") or t.get("market", {}).get("question", "")
        out.append({
            "trade_id":  t.get("id") or t.get("transactionHash") or f"{wallet}_{ts}",
            "wallet":    wallet,
            "username":  username,
            "whale_pnl": whale_pnl,
            "market_id": market_id,
            "token_id":  t.get("asset") or t.get("tokenId"),
            "question":  question,
            "category":  _bucket_category(t.get("category") or t.get("market", {}).get("category", "")),
            "direction": (t.get("side") or t.get("outcome") or "YES").upper(),
            "price":     float(t.get("price") or 0.5),
            "size":      float(t.get("usdcSize") or t.get("amount") or 0),
            "ts":        ts,
        })
    return out


def fetch_price_history(token_id: str, market_id: str) -> int:
    if not token_id:
        return 0
    try:
        r = requests.get(
            f"{GAMMA_API}/prices-history",
            params={"market": token_id, "interval": "max", "fidelity": 60},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"prices-history {token_id[:8]}: {e}")
        return 0
    history = data.get("history", []) if isinstance(data, dict) else []
    points = [{"ts": float(p["t"]), "price": float(p["p"])} for p in history if "t" in p and "p" in p]
    return save_market_prices(token_id, market_id, points)


def fetch_resolution(market_id: str) -> bool:
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={"conditionId": market_id}, timeout=15)
        data = r.json() if r.ok else []
    except Exception as e:
        logger.error(f"resolution {market_id[:10]}: {e}")
        return False
    if not (data and isinstance(data, list)):
        return False
    m = data[0]
    if not m.get("closed"):
        return False
    # Outcome prices: index 0 = YES. Resolved market settles to ~1/0.
    outcome_prices = m.get("outcomePrices") or m.get("outcome_prices")
    resolved_price = None
    if isinstance(outcome_prices, str):
        import json
        try:
            outcome_prices = json.loads(outcome_prices)
        except Exception:
            outcome_prices = None
    if isinstance(outcome_prices, list) and outcome_prices:
        try:
            resolved_price = float(outcome_prices[0])
        except Exception:
            resolved_price = None
    save_market_resolution({
        "market_id":        market_id,
        "question":         m.get("question", ""),
        "resolved_outcome": "YES" if (resolved_price or 0) >= 0.5 else "NO",
        "resolved_price":   resolved_price,
        "resolved_ts":      _ts(m.get("endDate") or m.get("endDateIso")),
    })
    return True


def run(n_whales: int = 30):
    init_db()
    leaderboard = get_leaderboard(limit=n_whales)
    whales = filter_whales(leaderboard)
    logger.info(f"Ingesting history for {len(whales)} whales...")

    all_markets: dict[str, str] = {}  # market_id -> token_id
    total_trades = 0
    for w in whales:
        wallet = w.get("proxyWallet")
        if not wallet:
            continue
        trades = fetch_wallet_trades(wallet, w.get("userName", wallet[:8]), w.get("pnl", 0))
        total_trades += save_historical_trades(trades)
        for t in trades:
            if t["market_id"] and t["market_id"] not in all_markets:
                all_markets[t["market_id"]] = t["token_id"]
        time.sleep(0.2)  # be polite to the API

    logger.info(f"Saved {total_trades} new trades across {len(all_markets)} markets")

    n_prices, n_resolved = 0, 0
    for market_id, token_id in all_markets.items():
        n_prices += fetch_price_history(token_id, market_id)
        if fetch_resolution(market_id):
            n_resolved += 1
        time.sleep(0.15)

    logger.info(f"Ingest complete: {total_trades} trades, {n_prices} price points, {n_resolved} resolutions")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--whales", type=int, default=30)
    args = ap.parse_args()
    run(n_whales=args.whales)
