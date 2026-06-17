"""
Backtest replay engine.

Feeds historical whale trades through the *real* decision stack — the same
consensus engine and committee used live — with a simulated clock and modeled
slippage, then scores each position against the market's actual resolution.

Key correctness properties:
  - No lookahead: prices come from ReplayFeed.price_at(token, cursor_ts), which
    only sees data at-or-before the event time.
  - Consensus is reconstructed from history: we replay record_bet() in timestamp
    order, exactly as the live buffer would have filled.
  - Walk-forward: thresholds are evaluated on a held-out later window. The split
    is by time, never random (markets are autocorrelated).
  - Honest costs: entries/exits fill at slippage-adjusted prices via SimExecutor.

The committee makes LLM calls, which are slow/costly, so by default the engine
runs in `fast` mode: it uses the deterministic consensus + a cheap edge proxy
instead of convening the full committee on every event. Pass `use_committee=True`
to validate the real committee on a (smaller) date range.

Run:  python3 -m backtest.engine [--split 0.7] [--committee] [--label name]
"""
import logging
import argparse
from datetime import datetime, timezone

from config import CONSENSUS_MIN_WHALES, BANKROLL, MAX_BET_PCT
from feed.replay_feed import ReplayFeed
from feed.sim_executor import SimExecutor
from whale import monitor
from risk.kelly import kelly_bet
from db.models import (
    get_historical_trades, get_market_resolution, save_backtest_run,
)

logger = logging.getLogger("backtest")


def _reset_consensus_buffer():
    monitor._recent_bets[:] = []


def _outcome_pnl(direction: str, entry_price: float, shares: float,
                 resolved_price: float) -> float:
    """PnL if held to resolution. YES settles at resolved_price (~1 or 0)."""
    exit_price = resolved_price if direction == "YES" else (1.0 - resolved_price)
    entry = entry_price if direction == "YES" else (1.0 - entry_price)
    return (exit_price - entry) * shares


def simulate(start_ts: float | None, end_ts: float | None,
             use_committee: bool = False, bankroll: float = BANKROLL,
             min_whales: int = CONSENSUS_MIN_WHALES) -> dict:
    """Run one pass over [start_ts, end_ts]. Returns metrics + per-trade results."""
    _reset_consensus_buffer()
    feed = ReplayFeed(start_ts, end_ts)
    execu = SimExecutor()

    processed: set = set()
    positions: list[dict] = []
    equity = bankroll
    peak = bankroll
    equity_curve: list[float] = []
    slippages: list[float] = []

    for ev in feed.events():
        # Replay into the consensus buffer exactly as live ingestion would.
        monitor.record_bet(ev.market_id, ev.direction, ev.wallet, ev.username,
                            ev.whale_pnl, ts=ev.ts)
        consensus = monitor.compute_consensus(ev.market_id, ev.direction, now=ev.ts)
        if not consensus.get("aligned"):
            continue

        key = (ev.market_id, ev.direction)
        if key in processed:
            continue
        processed.add(key)

        # Point-in-time entry price (no lookahead).
        price = feed.price_at(ev.token_id, ev.ts) or ev.price
        if price <= 0 or price >= 1:
            continue

        resolution = get_market_resolution(ev.market_id)
        if not resolution or resolution.get("resolved_price") is None:
            continue  # can't score an unresolved market

        # Edge estimate. With the committee this would be the calibrated prob;
        # in fast mode we use a consensus-scaled proxy edge so the harness can
        # sweep thresholds cheaply without thousands of LLM calls.
        consensus_score = consensus.get("consensus_score", 0.0)
        if use_committee:
            my_prob = _committee_prob(ev, price, consensus)
        else:
            # Proxy: lean toward the whale direction proportional to consensus.
            my_prob = min(0.97, price + 0.08 * consensus_score)

        size = kelly_bet(
            bankroll=equity, my_prob=my_prob, market_price=price,
            recent_outcomes=[1 if p["pnl"] > 0 else 0 for p in positions[-20:]],
            peak_bankroll=peak, persist=False,
        )
        size = max(0.0, min(size, equity * MAX_BET_PCT))
        if size <= 0:
            continue

        fill = execu.buy(ev.token_id or ev.market_id, ev.direction, size, price)
        slippages.append(abs(fill.slippage))

        pnl = _outcome_pnl(ev.direction, fill.fill_price, fill.shares,
                           float(resolution["resolved_price"]))
        equity += pnl
        peak = max(peak, equity)
        equity_curve.append(equity)
        positions.append({
            "market_id": ev.market_id, "question": ev.question[:60],
            "direction": ev.direction, "entry": fill.fill_price,
            "resolved_price": resolution["resolved_price"], "size": size,
            "pnl": round(pnl, 2), "consensus_score": consensus_score,
            "ts": ev.ts,
        })

    return _metrics(positions, equity_curve, bankroll, slippages)


def _committee_prob(ev, price: float, consensus: dict) -> float:
    """Convene the real committee for this event and return its (calibrated) prob."""
    from brain.committee import run_committee
    from risk.calibration import calibrate_probability
    from db.models import get_calibration_samples
    from whale.profiler import build_profile
    trade = ev.as_trade_dict()
    market = {"question": ev.question, "conditionId": ev.market_id,
              "category": ev.category, "days_to_expiry": 14}
    profile = build_profile(ev.wallet, ev.username, ev.whale_pnl)
    verdict = run_committee(trade, market, price, profile, [], BANKROLL, consensus)
    if verdict.get("verdict") != "APPROVE":
        return price  # no edge -> Kelly bets ~0
    raw = float(verdict.get("my_probability", price) or price)
    cal = calibrate_probability(raw, price, get_calibration_samples(500),
                                consensus.get("consensus_score", 0.0))
    return cal["calibrated_prob"]


def _metrics(positions: list[dict], equity_curve: list[float],
             start_bankroll: float, slippages: list[float]) -> dict:
    n = len(positions)
    if n == 0:
        return {"n_trades": 0, "win_rate": 0, "total_pnl": 0, "roi": 0,
                "sharpe": 0, "max_drawdown": 0, "avg_slippage": 0, "positions": []}
    wins = sum(1 for p in positions if p["pnl"] > 0)
    total_pnl = sum(p["pnl"] for p in positions)
    returns = [p["pnl"] / start_bankroll for p in positions]
    mean_r = sum(returns) / n
    var = sum((r - mean_r) ** 2 for r in returns) / n if n > 1 else 0.0
    std = var ** 0.5
    sharpe = (mean_r / std * (n ** 0.5)) if std > 0 else 0.0

    peak = start_bankroll
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)

    return {
        "n_trades":     n,
        "win_rate":     round(wins / n, 3),
        "total_pnl":    round(total_pnl, 2),
        "roi":          round(total_pnl / start_bankroll, 3),
        "sharpe":       round(sharpe, 3),
        "max_drawdown": round(max_dd, 3),
        "avg_slippage": round(sum(slippages) / len(slippages), 4) if slippages else 0.0,
        "positions":    positions,
    }


def walk_forward(split: float = 0.7, use_committee: bool = False,
                 label: str = "walkforward") -> dict:
    """
    Time-ordered train/test split. We report metrics on BOTH windows; the test
    window is the honest out-of-sample number. (Threshold tuning on train is left
    to the operator — this proves the split and surfaces overfit gaps.)
    """
    trades = get_historical_trades()
    if len(trades) < 10:
        logger.warning(f"Only {len(trades)} historical trades — ingest more before trusting results.")
    if not trades:
        return {"error": "no historical trades — run `python3 -m backtest.ingest` first"}

    ts_sorted = sorted(t["ts"] for t in trades)
    split_ts = ts_sorted[int(len(ts_sorted) * split)]
    t0, t1 = ts_sorted[0], ts_sorted[-1]

    logger.info(f"Train: {_d(t0)} → {_d(split_ts)} | Test: {_d(split_ts)} → {_d(t1)}")
    train = simulate(t0, split_ts, use_committee)
    test = simulate(split_ts, t1, use_committee)

    run = {
        "label":       label,
        "train_start": _d(t0), "train_end": _d(split_ts),
        "test_start":  _d(split_ts), "test_end": _d(t1),
        "n_trades":    test["n_trades"],
        "win_rate":    test["win_rate"],
        "total_pnl":   test["total_pnl"],
        "roi":         test["roi"],
        "sharpe":      test["sharpe"],
        "max_drawdown": test["max_drawdown"],
        "avg_slippage": test["avg_slippage"],
        "config":      {"split": split, "use_committee": use_committee,
                        "min_whales": CONSENSUS_MIN_WHALES},
        "results":     {"train": {k: v for k, v in train.items() if k != "positions"},
                        "test":  {k: v for k, v in test.items() if k != "positions"},
                        "test_positions": test["positions"][:100]},
    }
    run_id = save_backtest_run(run)
    logger.info(f"Saved backtest run #{run_id}")
    _print_summary(train, test)
    return run


def _d(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def _print_summary(train: dict, test: dict):
    print("\n" + "=" * 60)
    print(f"{'METRIC':<18}{'TRAIN (in-sample)':<22}{'TEST (out-of-sample)'}")
    print("-" * 60)
    for k in ("n_trades", "win_rate", "total_pnl", "roi", "sharpe", "max_drawdown", "avg_slippage"):
        print(f"{k:<18}{str(train.get(k)):<22}{test.get(k)}")
    print("=" * 60)
    if test["n_trades"] and train["n_trades"]:
        gap = train["roi"] - test["roi"]
        if gap > 0.5 * abs(train["roi"]) and train["roi"] > 0:
            print("⚠️  Large train→test ROI drop — likely overfit. Don't go live on this.")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", type=float, default=0.7)
    ap.add_argument("--committee", action="store_true", help="convene the real LLM committee (slow/costly)")
    ap.add_argument("--label", type=str, default="walkforward")
    args = ap.parse_args()
    walk_forward(split=args.split, use_committee=args.committee, label=args.label)
