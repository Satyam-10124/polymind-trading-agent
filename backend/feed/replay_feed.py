"""
ReplayFeed — a DataFeed backed by the historical_trades / market_prices tables.

Emits whale trades in timestamp order through a simulated clock, and answers
price_at() strictly from data at-or-before the cursor (no lookahead). This is
what lets the consensus engine + committee be validated on real history.
"""
import logging
from typing import Iterator
from feed.base import DataFeed, WhaleTradeEvent
from db.models import get_historical_trades, get_price_at

logger = logging.getLogger(__name__)


class ReplayFeed(DataFeed):
    def __init__(self, start_ts: float | None = None, end_ts: float | None = None):
        self.start_ts = start_ts
        self.end_ts = end_ts
        self._cursor = start_ts or 0.0
        self._rows = get_historical_trades(start_ts, end_ts)
        logger.info(f"ReplayFeed loaded {len(self._rows)} historical trades")

    def events(self) -> Iterator[WhaleTradeEvent]:
        for r in self._rows:
            self._cursor = float(r["ts"])
            yield WhaleTradeEvent(
                trade_id=r["trade_id"], wallet=r["wallet"], username=r.get("username", ""),
                whale_pnl=float(r.get("whale_pnl") or 0), market_id=r["market_id"],
                token_id=r.get("token_id"), question=r.get("question", ""),
                category=r.get("category", "other"), direction=r.get("direction", "YES"),
                price=float(r.get("price") or 0.5), size=float(r.get("size") or 0),
                ts=float(r["ts"]),
            )

    def price_at(self, token_id: str, ts: float | None = None) -> float | None:
        return get_price_at(token_id, ts if ts is not None else self._cursor)

    def now(self) -> float:
        return self._cursor
