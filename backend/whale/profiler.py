"""
Whale Profiler — builds per-wallet intelligence profiles.

Tracks:
  - avg bet size, top categories, recent streak
  - overall + PER-CATEGORY win rates (politics, crypto, sports, science, ...)
  - average hold duration (hours)
  - whether the whale tends to close early vs hold to resolution
  - "conviction signal" — does the whale build a position in multiple tranches
    (high conviction / accumulation) or one shot?

Profiles are cached in-memory and persisted to SQLite via db.save_whale_profile.
"""
import logging
import requests
from config import DATA_API

logger = logging.getLogger(__name__)

_profiles: dict[str, dict] = {}

# Category buckets we report win rates for. Anything else falls into "other".
CATEGORY_BUCKETS = ("politics", "crypto", "sports", "science")


def _fetch_wallet_history(wallet: str, limit: int = 100) -> list:
    try:
        r = requests.get(f"{DATA_API}/activity", params={"user": wallet, "limit": limit}, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Profile fetch for {wallet}: {e}")
        return []


def _bucket_category(raw: str) -> str:
    raw = (raw or "").lower()
    for bucket in CATEGORY_BUCKETS:
        if bucket in raw:
            return bucket
    # Common aliases.
    if any(k in raw for k in ("election", "president", "senate", "congress", "geopolit")):
        return "politics"
    if any(k in raw for k in ("btc", "eth", "bitcoin", "ethereum", "token", "defi")):
        return "crypto"
    if any(k in raw for k in ("nba", "nfl", "soccer", "football", "tennis", "match")):
        return "sports"
    return "other"


def _ts_of(trade: dict) -> float | None:
    ts = trade.get("timestamp") or trade.get("createdAt") or trade.get("time")
    if ts is None:
        return None
    if isinstance(ts, str):
        from datetime import datetime
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
    try:
        return float(ts)
    except Exception:
        return None


def build_profile(wallet: str, username: str = "", pnl: float = 0) -> dict:
    if wallet in _profiles:
        return _profiles[wallet]

    history = _fetch_wallet_history(wallet, limit=100)

    sizes       = []
    categories  = {}
    wins        = 0
    losses      = 0
    recent_pnl  = []

    # Per-category win/loss tallies.
    cat_wins:   dict[str, int] = {}
    cat_losses: dict[str, int] = {}

    # Hold-duration + close-behavior tracking.
    hold_hours_samples = []
    closed_early   = 0
    held_to_resol  = 0

    # Conviction (tranche) detection: count distinct buy actions per market.
    market_buys: dict[str, int] = {}

    for t in history:
        size = float(t.get("usdcSize") or t.get("amount") or 0)
        if size > 0:
            sizes.append(size)

        raw_cat = t.get("category") or t.get("market", {}).get("category", "other")
        bucket  = _bucket_category(raw_cat)
        categories[bucket] = categories.get(bucket, 0) + 1

        pnl_val = float(t.get("pnl") or 0)
        if pnl_val > 0:
            wins += 1
            cat_wins[bucket] = cat_wins.get(bucket, 0) + 1
        elif pnl_val < 0:
            losses += 1
            cat_losses[bucket] = cat_losses.get(bucket, 0) + 1
        recent_pnl.append(pnl_val)

        # Hold duration: entry ts → close/resolution ts when available.
        entry_ts = _ts_of(t)
        close_ts = None
        for key in ("closedAt", "resolvedAt", "exitTime"):
            v = t.get(key)
            if v:
                close_ts = _ts_of({"timestamp": v})
                break
        if entry_ts and close_ts and close_ts >= entry_ts:
            hold_hours_samples.append((close_ts - entry_ts) / 3600.0)

        # Close behavior: redeemed/resolved => held to resolution; sold => early.
        action = (t.get("type") or t.get("action") or t.get("side") or "").lower()
        if any(k in action for k in ("redeem", "resolve", "claim")):
            held_to_resol += 1
        elif "sell" in action:
            closed_early += 1

        # Tranche detection.
        mkt = (
            t.get("conditionId")
            or t.get("market", {}).get("conditionId")
            or t.get("slug")
            or t.get("title")
        )
        if mkt and ("buy" in action or action == "" or action in ("yes", "no")):
            market_buys[mkt] = market_buys.get(mkt, 0) + 1

    top_categories = sorted(categories, key=categories.get, reverse=True)[:3]
    avg_bet = sum(sizes) / len(sizes) if sizes else 100.0
    total   = wins + losses
    win_rate = wins / total if total > 0 else 0.5

    # Per-category win rates.
    category_win_rates = {}
    for bucket in set(list(cat_wins) + list(cat_losses)):
        w = cat_wins.get(bucket, 0)
        l = cat_losses.get(bucket, 0)
        if w + l > 0:
            category_win_rates[bucket] = round(w / (w + l), 3)

    # Hold metrics.
    avg_hold_hours = round(sum(hold_hours_samples) / len(hold_hours_samples), 1) if hold_hours_samples else 0.0
    close_total = closed_early + held_to_resol
    hold_to_resolution_pct = round(held_to_resol / close_total, 3) if close_total > 0 else 0.0
    closes_early = closed_early > held_to_resol

    # Conviction signal.
    multi_tranche_markets = sum(1 for n in market_buys.values() if n >= 2)
    total_markets = len(market_buys)
    avg_tranches = round(
        sum(market_buys.values()) / total_markets, 2
    ) if total_markets else 1.0
    if total_markets and multi_tranche_markets / total_markets >= 0.4:
        conviction_signal = "accumulator (multi-tranche)"
    elif avg_tranches > 1.2:
        conviction_signal = "mixed"
    else:
        conviction_signal = "one-shot"

    streak = 0
    for p in reversed(recent_pnl[-10:]):
        if p > 0:
            streak += 1
        else:
            break

    profile = {
        "wallet":          wallet,
        "username":        username,
        "pnl":             pnl,
        "avg_bet_size":    round(avg_bet, 2),
        "top_categories":  top_categories or ["Unknown"],
        "win_rate":        round(win_rate, 3),
        "recent_streak":   f"{streak} consecutive wins" if streak > 0 else "No recent streak",
        "total_trades":    total,
        "category_win_rates": category_win_rates,
        "avg_hold_hours":  avg_hold_hours,
        "closes_early":    closes_early,
        "hold_to_resolution_pct": hold_to_resolution_pct,
        "conviction_signal": conviction_signal,
        "avg_tranches":    avg_tranches,
    }
    _profiles[wallet] = profile
    return profile


def get_size_multiplier(wallet: str, current_size: float) -> float:
    profile = _profiles.get(wallet, {})
    avg = profile.get("avg_bet_size", 100)
    return round(current_size / avg, 2) if avg > 0 else 1.0


def invalidate(wallet: str):
    _profiles.pop(wallet, None)
