import requests
import time
import logging
from typing import Optional
from config import DATA_API, WHALE_MIN_PNL, WHALE_MIN_WIN_RATE, COPY_MAX_DELAY_SECS, BLOCK_CATEGORIES

logger = logging.getLogger(__name__)

seen_trade_ids: set = set()


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
    qualified = []
    for trader in leaderboard:
        pnl = trader.get("pnl", 0)
        vol = trader.get("vol", 0)
        if pnl < WHALE_MIN_PNL:
            continue
        win_rate = pnl / vol if vol > 0 else 0
        if win_rate < WHALE_MIN_WIN_RATE and pnl < 50000:
            continue
        trader["estimated_win_rate"] = round(win_rate, 3)
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


def is_blocked_category(market_question: str) -> bool:
    q = market_question.lower()
    return any(cat in q for cat in BLOCK_CATEGORIES)


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
            question = trade.get("title") or trade.get("market", {}).get("question", "")
            if is_blocked_category(question):
                logger.info(f"Blocked category trade: {question[:60]}")
                seen_trade_ids.add(trade_id)
                continue
            seen_trade_ids.add(trade_id)
            trade["whale_wallet"]    = wallet
            trade["whale_username"]  = whale.get("userName", wallet[:8])
            trade["whale_pnl"]       = whale.get("pnl", 0)
            trade["whale_win_rate"]  = whale.get("estimated_win_rate", 0)
            new_trades.append(trade)
            logger.info(f"New whale trade: {whale.get('userName')} → {question[:60]}")
    return new_trades
