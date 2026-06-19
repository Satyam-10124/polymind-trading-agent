import requests
import time
import logging
from typing import Optional
from config import (
    DATA_API, WHALE_MIN_PNL, WHALE_MIN_PNL_MARGIN, COPY_MAX_DELAY_SECS,
    BLOCK_CATEGORIES, CONSENSUS_MIN_WHALES, CONSENSUS_WINDOW_SECS,
)

logger = logging.getLogger(__name__)

seen_trade_ids: set = set()

# Rolling buffer of recent whale bets for consensus detection.
# Each entry: {market_id, direction, wallet, username, pnl, ts}
_recent_bets: list[dict] = []


def get_leaderboard(limit: int = 30) -> list[dict]:
    try:
        r = requests.get(
            f"{DATA_API}/v1/leaderboard",
            params={"sortBy": "PNL", "period": "ALL", "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Leaderboard fetch failed: {e}")
        return []


def filter_whales(leaderboard: list[dict]) -> list[dict]:
    """
    Coarse leaderboard pre-filter. Keeps traders with enough all-time PnL and a
    healthy profit margin per dollar traded (pnl / vol).

    `pnl_margin` is NOT a win rate — the leaderboard only exposes pnl and vol, not
    win/loss counts. It's a "does this trader actually make money" gate. The real
    per-wallet / per-category win rate is computed downstream from trade history
    in whale/profiler.py once a whale produces a trade worth evaluating.
    """
    qualified = []
    for trader in leaderboard:
        pnl = trader.get("pnl", 0)
        vol = trader.get("vol", 0)
        if pnl < WHALE_MIN_PNL:
            continue
        pnl_margin = pnl / vol if vol > 0 else 0
        if pnl_margin < WHALE_MIN_PNL_MARGIN and pnl < 50000:
            continue
        trader["pnl_margin"] = round(pnl_margin, 3)
        qualified.append(trader)
    return qualified


def get_whale_activity(wallet: str, limit: int = 5) -> list[dict]:
    try:
        r = requests.get(
            f"{DATA_API}/activity",
            params={"user": wallet, "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        return r.json() if isinstance(r.json(), list) else []
    except Exception as e:
        logger.error(f"Activity fetch for {wallet}: {e}")
        return []


def get_whale_positions(wallet: str) -> list[dict]:
    try:
        r = requests.get(
            f"{DATA_API}/positions",
            params={"user": wallet},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Positions fetch for {wallet}: {e}")
        return []


def is_trade_fresh(trade: dict) -> bool:
    ts = trade.get("timestamp") or trade.get("createdAt") or trade.get("time")
    if not ts:
        return False
    if isinstance(ts, str):
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:
            return False
    else:
        age = time.time() - float(ts)
    return age < COPY_MAX_DELAY_SECS


# Sports markets often carry no explicit "sports" keyword in the question text
# (e.g. "Will Canada win on 2026-06-18?", "Switzerland vs. Bosnia: O/U 2.5").
# These structural patterns catch the common game/match phrasings.
import re as _re
_SPORTS_PATTERNS = [
    _re.compile(r"\bvs\.?\b"),                       # "Team A vs. Team B"
    _re.compile(r"\bo/u\b|\bover/under\b"),          # totals
    _re.compile(r"\bwill .+ win on \d{4}-\d{2}-\d{2}"),  # daily game winners
    _re.compile(r"\bspread:?\b"),                    # point spreads
    _re.compile(r"\b\(-?\d+(\.\d+)?\)\b"),           # "(-1.5)" handicap lines
    _re.compile(r"\bexact score\b|\bto score\b|\bmoneyline\b"),
]


def is_blocked_category(market_question: str, category: str | None = None) -> bool:
    """
    True if the market should be skipped. Checks both the explicit category/tag
    (when available from Gamma) and structural sports phrasings in the question,
    since the data-api activity feed rarely tags the category.
    """
    q = (market_question or "").lower()
    if category and any(cat in category.lower() for cat in BLOCK_CATEGORIES):
        return True
    if any(cat in q for cat in BLOCK_CATEGORIES):
        return True
    return any(p.search(q) for p in _SPORTS_PATTERNS)


def normalize_direction(trade: dict) -> str | None:
    """
    Map a Polymarket activity record to a YES/NO direction for consensus + token
    selection, using the canonical `outcomeIndex` (0 -> YES/first token,
    1 -> NO/second token). Falls back to the `outcome` text for binary markets.

    The data-api `side` field is BUY/SELL (enter vs exit), NOT the outcome — using
    it as direction was a bug that copied trades onto the wrong token. Returns None
    if direction can't be determined.
    """
    idx = trade.get("outcomeIndex")
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        idx = None
    if idx in (0, 1):
        return "YES" if idx == 0 else "NO"
    outcome = (trade.get("outcome") or "").strip().lower()
    if outcome in ("yes", "no"):
        return outcome.upper()
    return None


def is_copyable_trade(trade: dict) -> bool:
    """
    Only mirror fresh position-OPENING trades. Skip:
      - REDEEM / settlement payouts (type != TRADE)
      - SELL legs (the whale is exiting, not entering)
    """
    ttype = (trade.get("type") or "").upper()
    side  = (trade.get("side") or "").upper()
    if ttype and ttype != "TRADE":
        return False
    if side and side != "BUY":
        return False
    return True


def _whale_tier_weight(pnl: float) -> float:
    """Map a whale's all-time PnL to a tier weight in [0.3, 1.0]."""
    if pnl >= 1_000_000:
        return 1.0
    if pnl >= 250_000:
        return 0.8
    if pnl >= 50_000:
        return 0.6
    if pnl >= 10_000:
        return 0.45
    return 0.3


def _prune_recent_bets(now: float | None = None):
    now = now or time.time()
    cutoff = now - CONSENSUS_WINDOW_SECS
    _recent_bets[:] = [b for b in _recent_bets if b["ts"] >= cutoff]


def record_bet(market_id: str, direction: str, wallet: str, username: str,
               pnl: float, ts: float | None = None):
    """Add a whale bet to the rolling consensus buffer."""
    if not market_id:
        return
    ts = ts or time.time()
    _prune_recent_bets(ts)
    # De-dupe: one vote per wallet per market+direction inside the window.
    for b in _recent_bets:
        if b["wallet"] == wallet and b["market_id"] == market_id and b["direction"] == direction:
            b["ts"] = ts
            return
    _recent_bets.append({
        "market_id": market_id, "direction": direction, "wallet": wallet,
        "username": username, "pnl": float(pnl or 0), "ts": ts,
    })


def compute_consensus(market_id: str, direction: str, now: float | None = None) -> dict:
    """
    Returns consensus info for a market+direction:
      {whale_count, consensus_score (0-1), whales: [...], aligned (bool)}

    consensus_score blends:
      - count factor   (how many whales agree, saturating at 5)
      - tier factor    (average tier weight of agreeing whales)
      - recency factor (more recent agreement scores higher)
    """
    now = now or time.time()
    _prune_recent_bets(now)
    agreeing = [
        b for b in _recent_bets
        if b["market_id"] == market_id and b["direction"] == direction
    ]
    count = len(agreeing)
    if count == 0:
        return {"whale_count": 0, "consensus_score": 0.0, "whales": [], "aligned": False}

    count_factor = min(count, 5) / 5.0
    tier_factor  = sum(_whale_tier_weight(b["pnl"]) for b in agreeing) / count
    recency_factor = sum(
        max(0.0, 1.0 - (now - b["ts"]) / CONSENSUS_WINDOW_SECS) for b in agreeing
    ) / count

    score = 0.5 * count_factor + 0.35 * tier_factor + 0.15 * recency_factor
    return {
        "whale_count":     count,
        "consensus_score": round(min(1.0, score), 3),
        "whales":          [{"username": b["username"], "pnl": b["pnl"]} for b in agreeing],
        "aligned":         count >= CONSENSUS_MIN_WHALES,
    }


def scan_new_whale_trades(whales: list[dict]) -> list[dict]:
    new_trades = []
    for whale in whales:
        wallet = whale.get("proxyWallet")
        if not wallet:
            continue
        activity = get_whale_activity(wallet, limit=3)
        for trade in activity:
            trade_id = trade.get("id") or trade.get("transactionHash")
            if not trade_id or trade_id in seen_trade_ids:
                continue
            if not is_trade_fresh(trade):
                continue
            # Only mirror fresh position-opening BUY trades (skip REDEEM/SELL).
            if not is_copyable_trade(trade):
                seen_trade_ids.add(trade_id)
                continue
            question = trade.get("title") or trade.get("market", {}).get("question", "")
            if is_blocked_category(question):
                logger.info(f"Blocked category trade: {question[:60]}")
                seen_trade_ids.add(trade_id)
                continue

            direction = normalize_direction(trade)
            if direction is None:
                # Non-binary outcome (e.g. multi-team spread) — can't map to YES/NO.
                seen_trade_ids.add(trade_id)
                continue

            seen_trade_ids.add(trade_id)
            trade["whale_wallet"]    = wallet
            trade["whale_username"]  = whale.get("userName", wallet[:8])
            trade["whale_pnl"]       = whale.get("pnl", 0)
            trade["whale_pnl_margin"] = whale.get("pnl_margin", 0)
            trade["direction"]       = direction

            # Feed the rolling consensus buffer.
            market_id = (
                trade.get("conditionId")
                or trade.get("market", {}).get("conditionId")
                or trade.get("market", {}).get("id")
                or trade.get("slug")
            )
            record_bet(
                market_id, direction, wallet,
                trade["whale_username"], trade["whale_pnl"],
            )

            new_trades.append(trade)
            logger.info(f"New whale trade: {whale.get('userName')} → {direction} {question[:55]}")
    return new_trades
