"""
Core feed/executor interfaces and the event shape they exchange.

Kept dependency-free (dataclasses + abc only) so both the live and backtest
implementations can import it without pulling in requests/websockets/clob.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, Optional


@dataclass
class WhaleTradeEvent:
    """A single whale trade, normalized across live and historical sources."""
    trade_id:   str
    wallet:     str
    username:   str
    whale_pnl:  float
    market_id:  str
    token_id:   Optional[str]
    question:   str
    category:   str
    direction:  str          # "YES" | "NO"
    price:      float        # price the whale traded at (0-1)
    size:       float        # USDC size
    ts:         float        # unix seconds
    raw:        dict = field(default_factory=dict)

    def as_trade_dict(self) -> dict:
        """Shape the rest of the pipeline (jobs/committee) already expects."""
        return {
            "id":              self.trade_id,
            "transactionHash": self.trade_id,
            "whale_wallet":    self.wallet,
            "whale_username":  self.username,
            "whale_pnl":       self.whale_pnl,
            "conditionId":     self.market_id,
            "token_id":        self.token_id,
            "title":           self.question,
            "question":        self.question,
            "category":        self.category,
            "side":            self.direction,
            "direction":       self.direction,
            "entry_price":     self.price,
            "usdcSize":        self.size,
            "whale_size":      self.size,
            "timestamp":       self.ts,
            **self.raw,
        }


@dataclass
class Fill:
    """Result of an execution attempt."""
    status:        str       # "filled" | "paper" | "error" | "rejected"
    token_id:      str
    side:          str
    size:          float     # USDC notionally spent
    requested_price: float
    fill_price:    float     # price actually paid after slippage/spread
    shares:        float
    slippage:      float = 0.0   # fill_price - requested_price
    order_id:      str = ""
    message:       str = ""


class DataFeed(ABC):
    """Source of whale trade events + point-in-time prices + a clock."""

    @abstractmethod
    def events(self) -> Iterator[WhaleTradeEvent]:
        """Yield whale trade events in chronological order."""
        ...

    @abstractmethod
    def price_at(self, token_id: str, ts: float | None = None) -> float | None:
        """Best available price for a token at time ts (no lookahead in backtest)."""
        ...

    @abstractmethod
    def now(self) -> float:
        """Current clock time (wall clock live; simulated cursor in backtest)."""
        ...


class Executor(ABC):
    @abstractmethod
    def buy(self, token_id: str, side: str, size: float, price: float) -> Fill: ...

    @abstractmethod
    def sell(self, token_id: str, shares: float, price: float) -> Fill: ...
