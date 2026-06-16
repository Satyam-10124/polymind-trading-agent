import uuid
import logging
import time
from datetime import datetime, timezone

from config import MAX_OPEN_POSITIONS, PAPER_MODE, CONSENSUS_MIN_WHALES
from whale.monitor import (
    get_leaderboard, filter_whales, scan_new_whale_trades, compute_consensus,
)
from whale.profiler import build_profile, get_size_multiplier
from brain.committee import run_committee, run_post_mortem
from risk.tp_sl_manager import check_position, compute_pnl, get_current_price
from executor.clob_client import place_order, sell_position, get_wallet_balance
from db.models import (
    save_position, close_position, get_open_positions,
    save_signal, get_stats, save_post_mortem, save_committee_report,
    save_consensus_event, save_whale_profile, save_lessons,
)

logger = logging.getLogger(__name__)

_telegram_send = None


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
    whales      = filter_whales(leaderboard)
    logger.info(f"Tracking {len(whales)} qualified whales")

    new_trades = scan_new_whale_trades(whales)
    if not new_trades:
        logger.info("No new whale trades detected")
        return

    balance  = get_wallet_balance()
    bankroll = balance

    for trade in new_trades:
        market_id = trade.get("conditionId") or trade.get("market", {}).get("conditionId")
        question  = trade.get("title") or trade.get("market", {}).get("question", "Unknown")

        import requests
        from config import GAMMA_API
        from datetime import datetime, timezone
        market = {}
        try:
            r = requests.get(f"{GAMMA_API}/markets", params={"conditionId": market_id}, timeout=10)
            if r.ok and r.json():
                market = r.json()[0]
        except Exception:
            market = {"question": question, "conditionId": market_id}

        expiry = market.get("endDate") or market.get("endDateIso", "")
        try:
            exp_dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
            days_to_expiry = max(0, (exp_dt - datetime.now(timezone.utc)).days)
        except Exception:
            days_to_expiry = 14
        market["days_to_expiry"] = days_to_expiry

        token_ids = market.get("clobTokenIds", [])
        side      = (trade.get("side") or trade.get("outcome") or "YES").upper()
        token_id  = token_ids[0] if side == "YES" and token_ids else (token_ids[1] if len(token_ids) > 1 else None)

        if not token_id:
            logger.warning(f"No token_id for {question[:50]}")
            continue

        current_price = get_current_price(token_id) or 0.5

        trade["direction"]   = side
        trade["entry_price"] = current_price
        trade["question"]    = question
        trade["category"]    = market.get("category", "other")
        trade["whale_size"]  = float(trade.get("usdcSize") or trade.get("amount") or 0)
        trade["trade_age_seconds"] = int(time.time() - float(trade.get("timestamp") or time.time()))

        # ── Multi-whale consensus filter ──
        # Only convene the (expensive) committee when CONSENSUS_MIN_WHALES
        # tracked whales have bet the same direction on this market within
        # the rolling window.
        consensus = compute_consensus(market_id, side)
        if not consensus.get("aligned"):
            logger.info(
                f"Consensus not reached for {question[:50]} — "
                f"{consensus.get('whale_count',0)}/{CONSENSUS_MIN_WHALES} whales {side}. Skipping."
            )
            continue

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
            continue

        bet_size = float(verdict.get("capital_allocation", 2.0))
        bet_size = max(1.0, min(bet_size, bankroll * 0.10))
        shares   = bet_size / current_price if current_price > 0 else 0

        place_order(token_id, side, bet_size, current_price)

        pos_id = str(uuid.uuid4())
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
            sell_qty = shares * 0.75
            sell_position(token_id, sell_qty, current)
            notify(
                f"💰 TAKE PROFIT (75%): {pos.get('question','?')[:50]}\n"
                f"Exit @ {current:.3f} | PnL: ${pnl * 0.75:+.2f}"
            )
            pos["shares"] = shares * 0.25
            pos["size"]   = pos["shares"] * entry_price

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
        {"start_bankroll": 50, "current_bankroll": get_wallet_balance(),
         "daily_pnl": stats["total_pnl"], "trades_count": stats["total_trades"],
         "win_rate": stats["win_rate"]},
        trades,
    )
    notify(f"📊 DAILY REPORT\n\n{report[:1000]}")


_post_mortem_done: set = set()


def post_mortem_job():
    """
    Runs after every closed trade — feeds outcome back to Claude for learning.
    Two Sigma's secret: every loss teaches the model something new.
    """
    from db.models import get_all_positions
    closed = [p for p in get_all_positions(limit=30) if p.get("status") == "closed"]

    for pos in closed:
        pos_id = pos.get("id")
        if pos_id in _post_mortem_done:
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
        _post_mortem_done.add(pos_id)

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
