"""
Data-feed + execution abstraction.

The strategy (consensus + committee + sizing) is decoupled from *where* trades
and prices come from and *how* orders fill, so the exact same decision code runs
against either:

  - LiveFeed  + LiveExecutor  -> production (REST/WebSocket + real or paper CLOB)
  - ReplayFeed + SimExecutor  -> backtest  (historical SQLite + modeled slippage)

A DataFeed yields WhaleTradeEvent objects and exposes a point-in-time price
accessor and a clock. An Executor turns a sizing decision into a fill (modeling
slippage in sim; calling the CLOB live).
"""
from feed.base import WhaleTradeEvent, DataFeed, Executor, Fill
from feed.slippage import apply_slippage

__all__ = ["WhaleTradeEvent", "DataFeed", "Executor", "Fill", "apply_slippage"]
