"""
Whale Profiler — builds per-wallet intelligence profiles.
Tracks: avg bet size, top categories, recent streak, category win rates.
"""
import logging
import requests
from config import DATA_API

logger = logging.getLogger(__name__)

_profiles: dict[str, dict] = {}


def _fetch_wallet_history(wallet: str, limit: int = 50) -> list:
    try:
        r = requests.get(f"{DATA_API}/activity", params={"user": wallet, "limit": limit}, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Profile fetch for {wallet}: {e}")
        return []


def build_profile(wallet: str, username: str = "", pnl: float = 0) -> dict:
    if wallet in _profiles:
        return _profiles[wallet]

    history = _fetch_wallet_history(wallet, limit=50)

    sizes       = []
    categories  = {}
    wins        = 0
    losses      = 0
    recent_pnl  = []

    for t in history:
        size = float(t.get("usdcSize") or t.get("amount") or 0)
        if size > 0:
            sizes.append(size)

        cat = t.get("category") or t.get("market", {}).get("category", "other")
        categories[cat] = categories.get(cat, 0) + 1

        outcome = t.get("outcome") or t.get("side", "")
        pnl_val = float(t.get("pnl") or 0)
        if pnl_val > 0:
            wins += 1
        elif pnl_val < 0:
            losses += 1
        recent_pnl.append(pnl_val)

    top_categories = sorted(categories, key=categories.get, reverse=True)[:3]
    avg_bet = sum(sizes) / len(sizes) if sizes else 100.0
    total   = wins + losses
    win_rate = wins / total if total > 0 else 0.5

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
    }
    _profiles[wallet] = profile
    return profile


def get_size_multiplier(wallet: str, current_size: float) -> float:
    profile = _profiles.get(wallet, {})
    avg = profile.get("avg_bet_size", 100)
    return round(current_size / avg, 2) if avg > 0 else 1.0


def invalidate(wallet: str):
    _profiles.pop(wallet, None)
