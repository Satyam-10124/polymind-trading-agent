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

from config import DATA_API, GAMMA_API, CLOB_API
from whale.monitor import get_leaderboard, filter_whales, is_copyable_trade, normalize_direction, normalize_ts
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
        return normalize_ts(v)
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
        # Same copyability + direction normalization as the live path, so the
        # backtest replays exactly what the live agent would have acted on.
        if not is_copyable_trade(t):
            continue
        direction = normalize_direction(t)
        if direction is None:
            continue
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
            "direction": direction,
            "price":     float(t.get("price") or 0.5),
            "size":      float(t.get("usdcSize") or t.get("amount") or 0),
            "ts":        ts,
        })
    return out


def fetch_price_history(token_id: str, market_id: str) -> int:
    if not token_id:
        return 0
    try:
        # NOTE: prices-history lives on the CLOB host, not Gamma. Verified against
        # the live API (Gamma returns 404 for this path).
        r = requests.get(
            f"{CLOB_API}/prices-history",
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
    """
    Authoritative resolution via the CLOB markets endpoint, which is keyed
    directly by condition_id (the Gamma /markets?conditionId filter is unreliable
    — it ignores the filter and returns arbitrary markets). The CLOB response
    carries per-token `winner` flags and settlement `price`.
    """
    try:
        r = requests.get(f"{CLOB_API}/markets/{market_id}", timeout=15)
        if not r.ok:
            return False
        m = r.json()
    except Exception as e:
        logger.error(f"resolution {market_id[:10]}: {e}")
        return False
    if not isinstance(m, dict) or not m.get("closed"):
        return False

    # Find the YES token; its settlement price (1=YES won, 0=NO won) is resolved_price.
    tokens = m.get("tokens") or []
    resolved_price = None
    for tok in tokens:
        if str(tok.get("outcome", "")).strip().lower() == "yes":
            try:
                resolved_price = float(tok.get("price"))
            except (TypeError, ValueError):
                resolved_price = 1.0 if tok.get("winner") else 0.0
            break
    if resolved_price is None:
        return False

    save_market_resolution({
        "market_id":        market_id,
        "question":         m.get("question", ""),
        "resolved_outcome": "YES" if resolved_price >= 0.5 else "NO",
        "resolved_price":   resolved_price,
        "resolved_ts":      _ts(m.get("end_date_iso") or m.get("endDate")),
    })
    return True


def run(n_whales: int = 30):
    init_db()
    leaderboard = get_leaderboard(limit=n_whales)
    whales = filter_whales(leaderboard)
    logger.info(f"Ingesting history for {len(whales)} whales...")

    # Collect every distinct (token, market) actually traded — both YES and NO
    # tokens of a market may be traded by different whales, and each needs its own
    # price history for no-lookahead replay.
    token_market: dict[str, str] = {}  # token_id -> market_id
    markets: set[str] = set()
    total_trades = 0
    for w in whales:
        wallet = w.get("proxyWallet")
        if not wallet:
            continue
        trades = fetch_wallet_trades(wallet, w.get("userName", wallet[:8]), w.get("pnl", 0))
        total_trades += save_historical_trades(trades)
        for t in trades:
            if t["token_id"]:
                token_market[t["token_id"]] = t["market_id"]
            if t["market_id"]:
                markets.add(t["market_id"])
        time.sleep(0.2)  # be polite to the API

    logger.info(f"Saved {total_trades} new trades across {len(markets)} markets, {len(token_market)} tokens")

    n_prices = 0
    for token_id, market_id in token_market.items():
        n_prices += fetch_price_history(token_id, market_id)
        time.sleep(0.1)

    n_resolved = 0
    for market_id in markets:
        if fetch_resolution(market_id):
            n_resolved += 1
        time.sleep(0.1)

    logger.info(f"Ingest complete: {total_trades} trades, {n_prices} price points, {n_resolved} resolutions")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--whales", type=int, default=30)
    args = ap.parse_args()
    run(n_whales=args.whales)
