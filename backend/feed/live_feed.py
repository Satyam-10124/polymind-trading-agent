"""
LiveFeed — real-time whale detection.

Design note (important, and a real constraint):
  Polymarket's public CLOB WebSocket `market` channel streams trade prints and
  order-book updates for the token ids you subscribe to, in real time. It does
  NOT tell you *which wallet* traded — wallet attribution only comes from the
  data-api `/activity` REST endpoint. So a pure-WS "see the whale instantly"
  feed is not possible on public infra.

  What we therefore do, and what actually reduces latency:
    1. WS market channel — subscribe to the tokens our tracked whales are active
       in. A large print on one of those tokens fires `on_print` immediately
       (sub-second), so we know *something* moved before the next REST poll.
    2. A fast `/activity` poll (driven by WS prints, or a short fallback timer)
       attributes the move to a wallet and feeds the consensus buffer.

  This collapses the detection half of the latency budget from up to
  SCAN_INTERVAL (30s) down to "as soon as the print lands + one activity fetch",
  and the committee half is cut by the model cascade + stage-1 parallelization.

Falls back cleanly to periodic polling if `websockets` is missing or the socket
can't connect — mirroring the optional-import pattern used for telegram/clob.
"""
import json
import time
import asyncio
import logging
import threading

from config import WS_URL, USE_WEBSOCKET, WHALE_REFRESH_SECS
from whale.monitor import (
    get_leaderboard, filter_whales, filter_whales_by_recency, scan_new_whale_trades,
)

logger = logging.getLogger(__name__)

try:
    import websockets  # noqa: F401
    _ws_available = True
except ImportError:
    _ws_available = False
    logger.warning("websockets not installed — LiveFeed will use polling fallback")


class LiveFeed:
    """
    Runs in a background thread. Calls `on_consensus_trade(trade)` for each fresh
    whale trade so the scheduler can evaluate consensus + (maybe) convene the
    committee — event-driven instead of on a fixed 30s tick.
    """

    def __init__(self, on_consensus_trade):
        self.on_consensus_trade = on_consensus_trade
        self._whales: list[dict] = []
        self._tracked_tokens: set[str] = set()
        self._last_whale_refresh = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── lifecycle ──────────────────────────────────────────────
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="LiveFeed")
        self._thread.start()
        logger.info(f"LiveFeed started ({'websocket' if (USE_WEBSOCKET and _ws_available) else 'polling'} mode)")

    def stop(self):
        self._stop.set()

    # ── whale set refresh (REST, slow) ─────────────────────────
    def _refresh_whales(self):
        now = time.time()
        if now - self._last_whale_refresh < WHALE_REFRESH_SECS and self._whales:
            return
        leaderboard = get_leaderboard(limit=30)
        self._whales = filter_whales_by_recency(filter_whales(leaderboard))
        self._last_whale_refresh = now
        logger.info(f"LiveFeed refreshed whale set: {len(self._whales)} qualified")

    # ── attribution poll (REST, fast) ─────────────────────────
    def _scan_and_dispatch(self):
        """Fetch fresh whale trades and dispatch each to the consensus callback."""
        self._refresh_whales()
        try:
            new_trades = scan_new_whale_trades(self._whales)
        except Exception as e:
            logger.error(f"LiveFeed scan failed: {e}")
            return
        for trade in new_trades:
            tok = trade.get("token_id") or trade.get("asset")
            if tok:
                self._tracked_tokens.add(tok)
            try:
                self.on_consensus_trade(trade)
            except Exception as e:
                logger.error(f"on_consensus_trade failed: {e}")

    # ── main loop ──────────────────────────────────────────────
    def _run(self):
        if USE_WEBSOCKET and _ws_available:
            try:
                asyncio.run(self._ws_loop())
                return
            except Exception as e:
                logger.error(f"WS loop crashed, falling back to polling: {e}")
        self._poll_loop()

    def _poll_loop(self):
        """Fallback: a tighter poll than the old scheduler tick."""
        from config import SCAN_INTERVAL
        interval = max(5, min(SCAN_INTERVAL, 15))
        while not self._stop.is_set():
            self._scan_and_dispatch()
            self._stop.wait(interval)

    async def _ws_loop(self):
        import websockets
        backoff = 1
        while not self._stop.is_set():
            try:
                async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                    backoff = 1
                    await self._subscribe(ws)
                    logger.info("LiveFeed WS connected")
                    # Prime the whale set + tokens once on connect.
                    self._scan_and_dispatch()
                    last_resub = time.time()
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        await self._handle_ws_message(ws, raw)
                        # Periodically re-subscribe to newly-tracked tokens.
                        if time.time() - last_resub > 30:
                            await self._subscribe(ws)
                            last_resub = time.time()
            except Exception as e:
                if self._stop.is_set():
                    break
                logger.warning(f"WS disconnected ({e}); reconnecting in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _subscribe(self, ws):
        self._refresh_whales()
        if not self._tracked_tokens:
            # Nothing to watch yet; an initial scan will populate tokens.
            return
        msg = {"type": "market", "assets_ids": list(self._tracked_tokens)[:200]}
        try:
            await ws.send(json.dumps(msg))
        except Exception as e:
            logger.error(f"WS subscribe failed: {e}")

    async def _handle_ws_message(self, ws, raw):
        """A trade print on a tracked token => attribute via a fast activity scan."""
        try:
            data = json.loads(raw)
        except Exception:
            return
        events = data if isinstance(data, list) else [data]
        relevant = any(
            (e.get("event_type") in ("last_trade_price", "trade") or e.get("type") == "trade")
            for e in events if isinstance(e, dict)
        )
        if relevant:
            # Offload the (blocking) REST attribution to a thread so we don't
            # stall the socket read loop.
            await asyncio.to_thread(self._scan_and_dispatch)
