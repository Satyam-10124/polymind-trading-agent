import uuid
import logging
import time
from datetime import datetime, timezone

from config import MAX_OPEN_POSITIONS, PAPER_MODE, CONSENSUS_MIN_WHALES, PEAK_BANKROLL, MIN_CLAUDE_SCORE, BANKROLL, MAX_BET_PCT, PARTIAL_TP_SELL_PCT
from risk.kelly import kelly_bet
from whale.monitor import (
    get_leaderboard, filter_whales, filter_whales_by_recency,
    scan_new_whale_trades, compute_consensus, normalize_ts,
)
from whale.profiler import build_profile, get_size_multiplier
from brain.committee import run_committee, run_post_mortem, derive_event_key, _resolve_day
from risk.tp_sl_manager import check_position, compute_pnl, get_current_price
from executor.clob_client import place_order, sell_position, get_wallet_balance
from db.models import (
    save_position, close_position, update_position, get_open_positions,
    save_signal, get_stats, save_post_mortem, save_committee_report,
    save_consensus_event, save_whale_profile, save_lessons, get_recent_outcomes,
    mark_lessons_applied, get_recent_lessons_for_category,
    dedup_contains, dedup_mark,
)

logger = logging.getLogger(__name__)

_telegram_send = None

# Persisted dedup scopes (see db.models.dedup_*). These replace the old
# in-memory sets so dedup survives restarts and stays memory-bounded:
#   _CONSENSUS_SCOPE   — (market_id, side) pairs already sent to the committee,
#                        so the same consensus doesn't re-trigger every scan.
#   _POST_MORTEM_SCOPE — position ids already post-mortemed.
_CONSENSUS_SCOPE   = "consensus_processed"
_POST_MORTEM_SCOPE = "post_mortem_done"


def set_telegram(fn):
    global _telegram_send
    _telegram_send = fn


def notify(msg: str):
    if _telegram_send:
        try:
            _telegram_send(msg)
        except Exception as e:
            logger.error(f"Telegram notify failed: {e}")
    logger.info(f"[NOTIFY] {msg}")


def whale_scan_job():
    logger.info("── Whale scan started (Institutional Committee Mode) ──")
    open_pos = get_open_positions()
    if len(open_pos) >= MAX_OPEN_POSITIONS:
        logger.info(f"Max positions reached ({MAX_OPEN_POSITIONS}), skipping scan")
        return

    leaderboard = get_leaderboard(limit=30)
    whales      = filter_whales_by_recency(filter_whales(leaderboard))
    logger.info(f"Tracking {len(whales)} qualified whales")

    new_trades = scan_new_whale_trades(whales)
    if not new_trades:
        logger.info("No new whale trades detected")
        return

    balance  = get_wallet_balance()
    bankroll = balance

    for trade in new_trades:
        process_whale_trade(trade, open_pos, bankroll)


def process_whale_trade(trade: dict, open_pos: list | None = None,
                        bankroll: float | None = None):
    """
    Evaluate a single fresh whale trade: enrich market data, apply the consensus
    gate, and (if aligned) convene the committee + size + execute.

    Extracted from whale_scan_job so the event-driven LiveFeed can call it the
    instant a trade is detected, instead of waiting for the next polling tick.
    Both entry points share this body, so behavior is identical.
    """
    if open_pos is None:
        open_pos = get_open_positions()
    if len(open_pos) >= MAX_OPEN_POSITIONS:
        logger.info(f"Max positions reached ({MAX_OPEN_POSITIONS}), skipping trade")
        return
    if bankroll is None:
        bankroll = get_wallet_balance()

    if True:
        market_id = trade.get("conditionId") or trade.get("market", {}).get("conditionId")
        question  = trade.get("title") or trade.get("market", {}).get("question", "Unknown")

        import requests, json as _json
        from config import GAMMA_API
        from datetime import datetime, timezone
        market = {"question": question, "conditionId": market_id}
        if market_id:
            try:
                r = requests.get(f"{GAMMA_API}/markets", params={"conditionId": market_id}, timeout=10)
                data = r.json() if r.ok else []
                if data and isinstance(data, list):
                    candidate = data[0]
                    # Only accept if the conditionId actually matches
                    if candidate.get("conditionId") == market_id or not candidate.get("conditionId"):
                        market = candidate
            except Exception:
                pass

        expiry = market.get("endDate") or market.get("endDateIso", "")
        try:
            exp_dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
            days_to_expiry = max(0, (exp_dt - datetime.now(timezone.utc)).days)
        except Exception:
            days_to_expiry = 14
        market["days_to_expiry"] = days_to_expiry

        raw_token_ids = market.get("clobTokenIds", [])
        if isinstance(raw_token_ids, str):
            try:
                raw_token_ids = _json.loads(raw_token_ids)
            except Exception:
                raw_token_ids = []
        token_ids = raw_token_ids if isinstance(raw_token_ids, list) else []

        # Direction was normalized from outcomeIndex in scan_new_whale_trades.
        side = (trade.get("direction") or "YES").upper()
        outcome_idx = 0 if side == "YES" else 1

        # Prefer the exact token the whale traded (activity `asset`); otherwise
        # index into the market's token array by outcome.
        token_id = trade.get("asset") or trade.get("token_id")
        if not token_id and token_ids:
            token_id = token_ids[outcome_idx] if len(token_ids) > outcome_idx else token_ids[0]

        if not token_id:
            logger.warning(f"No token_id for {question[:50]}")
            return

        current_price = get_current_price(token_id) or 0.5

        trade["direction"]   = side
        trade["entry_price"] = current_price
        trade["question"]    = question
        trade["category"]    = market.get("category", "other")
        trade["whale_size"]  = float(trade.get("usdcSize") or trade.get("amount") or 0)
        trade_ts = normalize_ts(trade.get("timestamp"))
        if trade_ts is None:
            trade_ts = time.time()
        trade["trade_age_seconds"] = int(time.time() - trade_ts)

        # ── Multi-whale consensus filter ──
        # Only convene the (expensive) committee when CONSENSUS_MIN_WHALES
        # tracked whales have bet the same direction on this market within
        # the rolling window.
        consensus_key = f"{market_id}|{side}"
        if dedup_contains(_CONSENSUS_SCOPE, consensus_key):
            logger.debug(f"Consensus already processed for {question[:50]}, skipping.")
            return

        consensus = compute_consensus(market_id, side)
        if not consensus.get("aligned"):
            logger.info(
                f"Consensus not reached for {question[:50]} — "
                f"{consensus.get('whale_count',0)}/{CONSENSUS_MIN_WHALES} whales {side}. Skipping."
            )
            return

        dedup_mark(_CONSENSUS_SCOPE, consensus_key)

        logger.info(
            f"🐳 CONSENSUS: {consensus['whale_count']} whales aligned {side} "
            f"(score {consensus['consensus_score']:.2f}) on {question[:50]}"
        )
        save_consensus_event({
            "market_id":       market_id,
            "question":        question,
            "direction":       side,
            "whale_count":     consensus["whale_count"],
            "consensus_score": consensus["consensus_score"],
            "whales":          consensus["whales"],
        })
        whale_names = ", ".join(w["username"] for w in consensus["whales"][:5])
        notify(
            f"🐳 *CONSENSUS TRIGGER* ({consensus['whale_count']} whales aligned)\n"
            f"Market: {question[:55]}\n"
            f"Direction: {side} | Score: {consensus['consensus_score']:.2f}\n"
            f"Whales: {whale_names}\n"
            f"→ Convening Investment Committee..."
        )

        whale_wallet  = trade.get("whale_wallet", "")
        whale_profile = build_profile(whale_wallet, trade.get("whale_username", ""), trade.get("whale_pnl", 0))
        try:
            save_whale_profile(whale_profile)
        except Exception as e:
            logger.error(f"save_whale_profile failed: {e}")

        verdict = run_committee(
            trade         = trade,
            market        = market,
            current_price = current_price,
            whale_profile = whale_profile,
            open_positions = open_pos,
            bankroll      = bankroll,
            consensus     = consensus,
        )

        # Enforce the minimum committee conviction. An APPROVE below
        # MIN_CLAUDE_SCORE is downgraded to WATCH so it is logged and surfaced
        # but never sized or executed. (The committee path otherwise ignores
        # this floor — only the legacy single-pass analyst applied it.)
        if verdict.get("verdict") == "APPROVE" and \
                int(verdict.get("conviction", 0) or 0) < MIN_CLAUDE_SCORE:
            logger.info(
                f"Conviction {verdict.get('conviction')}/10 below MIN_CLAUDE_SCORE "
                f"({MIN_CLAUDE_SCORE}) — downgrading APPROVE → WATCH for {question[:50]}"
            )
            notify(
                f"🟡 Committee APPROVE downgraded → WATCH (low conviction)\n"
                f"Market: {question[:55]}\n"
                f"Conviction: {verdict.get('conviction',0)}/10 < {MIN_CLAUDE_SCORE} threshold\n"
                f"No order placed."
            )
            verdict["verdict"] = "WATCH"

        save_signal({
            "question":        question,
            "market_id":       market_id,
            "direction":       verdict.get("direction"),
            "score":           verdict.get("conviction", 0),
            "edge":            verdict.get("edge", 0),
            "reasoning":       verdict.get("reasoning"),
            "key_facts":       [],
            "action":          "trade" if verdict.get("verdict") == "APPROVE" else "skip",
            "consensus_score": consensus.get("consensus_score", 0),
        })

        if verdict.get("verdict") != "APPROVE":
            cro = verdict.get("committee_reports", {}).get("cro", {})
            notify(
                f"🏛 Committee: {verdict.get('verdict')} | {question[:50]}\n"
                f"Conviction: {verdict.get('conviction',0)}/10\n"
                f"Reason: {verdict.get('reasoning','')[:150]}\n"
                f"CRO flaws: {', '.join(cro.get('fatal_flaws',['none'])[:2])}"
            )
            return

        pos_id = str(uuid.uuid4())

        # Enhanced Kelly: recompute size with dynamic fraction + drawdown breaker,
        # logging the full breakdown to SQLite. Take the more conservative of the
        # committee's allocation and the Kelly-sized bet.
        my_prob   = float(verdict.get("my_probability", current_price) or current_price)
        recent    = get_recent_outcomes(limit=20)

        # Calibrate the committee's stated probability against its own historical
        # track record before it ever reaches Kelly. An overconfident `my_prob`
        # makes Kelly over-bet; this shrinks it toward the market price, weighted
        # by measured calibration and consensus strength, and caps the edge claim.
        from risk.calibration import calibrate_probability
        from db.models import get_calibration_samples
        try:
            cal = calibrate_probability(
                my_prob         = my_prob,
                market_price    = current_price,
                samples         = get_calibration_samples(limit=500),
                consensus_score = consensus.get("consensus_score", 0.0),
            )
            my_prob = cal["calibrated_prob"]
        except Exception as e:
            logger.error(f"calibration failed, using raw prob: {e}")

        kelly_size = kelly_bet(
            bankroll        = bankroll,
            my_prob         = my_prob,
            market_price    = current_price,
            recent_outcomes = recent,
            peak_bankroll   = max(PEAK_BANKROLL, bankroll),
            position_id     = pos_id,
            question        = question,
        )
        committee_size = float(verdict.get("capital_allocation", 2.0))
        bet_size = min(committee_size, kelly_size) if kelly_size > 0 else committee_size
        bet_size = max(1.0, min(bet_size, bankroll * MAX_BET_PCT))
        shares   = bet_size / current_price if current_price > 0 else 0

        place_order(token_id, side, bet_size, current_price)

        pos = {
            "id":           pos_id,
            "question":     question,
            "market_id":    market_id,
            "token_id":     token_id,
            "direction":    side,
            "entry_price":  current_price,
            "size":         bet_size,
            "shares":       shares,
            "source":       "whale_committee",
            "whale_name":   trade.get("whale_username", "Unknown"),
            "claude_score": verdict.get("conviction"),
            "reasoning":    verdict.get("reasoning"),
            "category":     market.get("category", "other"),
            "consensus_score": consensus.get("consensus_score", 0),
            "resolve_date": _resolve_day(market),
            "event_key":    derive_event_key(question, market.get("category", "other")),
        }
        save_position(pos)
        save_committee_report(pos_id, question, verdict)

        reports  = verdict.get("committee_reports", {})
        eff      = reports.get("efficiency", {})
        cro      = reports.get("cro", {})
        archetype = reports.get("archetype", {})
        mode_tag = "[PAPER] " if PAPER_MODE else ""

        notify(
            f"🟢 {mode_tag}COMMITTEE APPROVED\n"
            f"Market: {question[:55]}\n"
            f"Side: {side} @ {current_price*100:.1f}¢ | Size: ${bet_size:.2f}\n"
            f"Conviction: {verdict.get('conviction')}/10 | "
            f"Archetype: {archetype.get('archetype','?')}\n"
            f"Efficiency: {eff.get('efficiency_state','?')} | "
            f"Mispricing: {eff.get('mispricing_confidence',0):.0f}%\n"
            f"CRO: {cro.get('rejection_probability',0):.0f}% rejection risk\n"
            f"Thesis: {verdict.get('reasoning','')[:180]}"
        )
        logger.info(f"Committee-approved position opened: {pos_id} | {question[:50]}")


def position_check_job():
    logger.info("── Position check started ──")
    open_pos = get_open_positions()
    if not open_pos:
        return

    for pos in open_pos:
        signal = check_position(pos)
        if signal == "hold":
            continue

        token_id    = pos.get("token_id")
        shares      = float(pos.get("shares", 0))
        entry_price = float(pos.get("entry_price", 0.5))
        current     = get_current_price(token_id) or entry_price
        pnl         = (current - entry_price) * shares

        if signal == "take_profit_partial":
            # Fire the partial exit once per position. check_position keys off
            # price alone, so without this flag the reloaded full share count
            # would re-trigger the sell on every subsequent check.
            if int(pos.get("partial_tp_done", 0)):
                continue
            sell_qty       = shares * PARTIAL_TP_SELL_PCT
            remaining      = shares - sell_qty
            sell_position(token_id, sell_qty, current)
            notify(
                f"💰 TAKE PROFIT ({PARTIAL_TP_SELL_PCT*100:.0f}%): {pos.get('question','?')[:50]}\n"
                f"Exit @ {current:.3f} | PnL: ${pnl * PARTIAL_TP_SELL_PCT:+.2f}"
            )
            # Persist the reduced position and mark the partial done.
            update_position(pos["id"], remaining, remaining * entry_price,
                            partial_tp_done=True)

        elif signal in ("take_profit_full", "stop_loss", "time_stop"):
            sell_position(token_id, shares, current)
            close_position(pos["id"], current, pnl, signal)
            emoji = "💰" if pnl > 0 else "🔴"
            label = {"take_profit_full": "TAKE PROFIT", "stop_loss": "STOP LOSS", "time_stop": "TIME STOP"}[signal]
            notify(
                f"{emoji} {label}: {pos.get('question','?')[:50]}\n"
                f"Entry: {entry_price:.3f} → Exit: {current:.3f}\n"
                f"PnL: ${pnl:+.2f}"
            )


def daily_report_job():
    from brain.claude_agent import generate_daily_report
    from db.models import get_all_positions
    stats  = get_stats()
    trades = get_all_positions(limit=20)
    report = generate_daily_report(
        {"start_bankroll": BANKROLL, "current_bankroll": get_wallet_balance(),
         "daily_pnl": stats["total_pnl"], "trades_count": stats["total_trades"],
         "win_rate": stats["win_rate"]},
        trades,
    )
    notify(f"📊 DAILY REPORT\n\n{report[:1000]}")


def post_mortem_job():
    """
    Runs after every closed trade — feeds outcome back to Claude for learning.
    Two Sigma's secret: every loss teaches the model something new.
    """
    from db.models import get_all_positions
    closed = [p for p in get_all_positions(limit=30) if p.get("status") == "closed"]

    for pos in closed:
        pos_id = pos.get("id")
        if dedup_contains(_POST_MORTEM_SCOPE, pos_id):
            continue

        opened = pos.get("opened_at", "")
        closed_at = pos.get("closed_at", "")
        hold_days = 0
        try:
            from datetime import datetime, timezone
            o = datetime.fromisoformat(str(opened).replace("Z", "+00:00"))
            c = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
            hold_days = max(0, (c - o).days)
        except Exception:
            pass

        pos["hold_days"] = hold_days
        report = run_post_mortem(pos)
        save_post_mortem(pos, report)

        # Learning loop: explode lessons into the lessons_learned table, and
        # update whether the lessons we previously injected for this category
        # actually reduced losses (a win => helped) or were ignored (a loss).
        category = pos.get("category", "other")
        try:
            save_lessons(pos, report)
            mark_lessons_applied(category, helped=float(pos.get("pnl", 0)) > 0)
        except Exception as e:
            logger.error(f"lessons persist failed: {e}")

        dedup_mark(_POST_MORTEM_SCOPE, pos_id)

        lessons_text = " | ".join(report.get("lessons", [])[:2])
        edge_real    = "✅ Real edge" if report.get("edge_was_real") else "❌ Phantom edge"
        pnl          = float(pos.get("pnl", 0))

        logger.info(
            f"Post-mortem [{pos_id[:8]}]: edge_real={report.get('edge_was_real')} "
            f"thesis={report.get('thesis_correct')} lessons={len(report.get('lessons',[]))}"
        )
        notify(
            f"🧠 POST-MORTEM: {pos.get('question','?')[:50]}\n"
            f"PnL: ${pnl:+.2f} | {edge_real}\n"
            f"Lessons: {lessons_text[:200]}\n"
            f"Future rule: {report.get('future_rules',['none'])[0][:120] if report.get('future_rules') else 'none'}"
        )
