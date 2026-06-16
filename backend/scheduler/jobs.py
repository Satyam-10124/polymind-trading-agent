import uuid
import logging
from datetime import datetime, timezone

from config import MAX_OPEN_POSITIONS, PAPER_MODE
from whale.monitor import get_leaderboard, filter_whales, scan_new_whale_trades
from brain.claude_agent import analyse_whale_trade, should_trade
from risk.kelly import kelly_bet, get_current_bankroll
from risk.tp_sl_manager import check_position, compute_pnl, get_current_price
from executor.clob_client import place_order, sell_position, get_wallet_balance
from db.models import (
    save_position, close_position,
    get_open_positions, save_signal, get_stats
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
    logger.info("── Whale scan started ──")
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
    bankroll = get_current_bankroll(wallet_balance=balance)

    for trade in new_trades:
        market_id = trade.get("conditionId") or trade.get("market", {}).get("conditionId")
        question  = trade.get("title") or trade.get("market", {}).get("question", "Unknown")

        import requests
        from config import GAMMA_API
        market = {}
        try:
            r = requests.get(f"{GAMMA_API}/markets", params={"conditionId": market_id}, timeout=10)
            if r.ok and r.json():
                market = r.json()[0]
        except Exception:
            market = {"question": question, "conditionId": market_id}

        token_ids = market.get("clobTokenIds", [])
        side      = (trade.get("side") or trade.get("outcome") or "YES").upper()
        token_id  = token_ids[0] if side == "YES" and token_ids else (token_ids[1] if len(token_ids) > 1 else None)

        if not token_id:
            logger.warning(f"No token_id for {question[:50]}")
            continue

        current_price = get_current_price(token_id) or 0.5

        decision = analyse_whale_trade(trade, market, current_price)
        save_signal({
            **decision,
            "action": "trade" if should_trade(decision) else "skip",
        })

        if not should_trade(decision):
            logger.info(
                f"SKIP: score={decision.get('score',0)} "
                f"edge={decision.get('edge',0):.3f} → {question[:50]}"
            )
            notify(
                f"🔍 Analysed: {question[:50]}\n"
                f"Score: {decision.get('score',0)}/10 → SKIP\n"
                f"Reason: {decision.get('reasoning','')[:120]}"
            )
            continue

        my_prob    = decision.get("my_probability", current_price)
        bet_size   = kelly_bet(bankroll, my_prob, current_price)
        shares     = bet_size / current_price if current_price > 0 else 0

        result = place_order(token_id, side, bet_size, current_price)

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
            "source":       "whale",
            "whale_name":   trade.get("whale_username", "Unknown"),
            "claude_score": decision.get("score"),
            "reasoning":    decision.get("reasoning"),
        }
        save_position(pos)

        mode_tag = "[PAPER] " if PAPER_MODE else ""
        notify(
            f"🟢 {mode_tag}COPIED WHALE TRADE\n"
            f"Whale: {trade.get('whale_username','?')} (PnL: ${trade.get('whale_pnl',0):,.0f})\n"
            f"Market: {question[:60]}\n"
            f"Side: {side} @ {current_price:.2f}¢\n"
            f"Size: ${bet_size:.2f} | Score: {decision.get('score')}/10\n"
            f"Edge: {decision.get('edge',0):+.3f}\n"
            f"Reason: {decision.get('reasoning','')[:150]}"
        )
        logger.info(f"Position opened: {pos_id} | {question[:50]}")


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
