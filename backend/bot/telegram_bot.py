import logging
import threading
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAPER_MODE
from db.models import (
    get_stats, get_open_positions, get_all_positions,
    get_whale_profiles, get_committee_report, get_lessons,
)
from executor.clob_client import get_wallet_balance
from risk.tp_sl_manager import compute_pnl, get_current_price

logger = logging.getLogger(__name__)

_paused = False


def is_paused():
    return _paused


try:
    import telebot
    _bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN != "FILL_THIS_IN" else None
except ImportError:
    _bot = None
    logger.warning("pyTelegramBotAPI not installed")


def send_message(text: str):
    if not _bot or not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "FILL_THIS_IN":
        print(f"[TG] {text}")
        return
    try:
        _bot.send_message(TELEGRAM_CHAT_ID, text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"TG send failed: {e}")


def _fmt_stats() -> str:
    stats   = get_stats()
    balance = get_wallet_balance()
    mode    = "📄 PAPER MODE" if PAPER_MODE else "🔴 LIVE MODE"
    paused  = "⏸ PAUSED" if _paused else "▶️ RUNNING"
    return (
        f"*PolyMind Status*\n"
        f"{mode} | {paused}\n\n"
        f"💰 Balance: ${balance:.2f} USDC\n"
        f"📈 Total PnL: ${stats['total_pnl']:+.2f}\n"
        f"🎯 Win Rate: {stats['win_rate']}%\n"
        f"📊 Trades: {stats['total_trades']} total | {stats['open_positions']} open\n"
        f"✅ {stats['wins']} wins | ❌ {stats['losses']} losses"
    )


def _fmt_positions() -> str:
    positions = get_open_positions()
    if not positions:
        return "📭 No open positions"
    lines = ["*Open Positions*\n"]
    for p in positions:
        current = get_current_price(p.get("token_id")) or p.get("entry_price", 0)
        pnl     = compute_pnl(p)
        emoji   = "📈" if pnl >= 0 else "📉"
        lines.append(
            f"{emoji} {p.get('question','?')[:45]}\n"
            f"   {p.get('direction')} @ {float(p.get('entry_price',0)):.3f} → {current:.3f} | PnL: ${pnl:+.2f}\n"
            f"   Source: {p.get('whale_name','?')} | Score: {p.get('claude_score','?')}/10\n"
        )
    return "\n".join(lines)


def _fmt_history() -> str:
    trades = get_all_positions(limit=10)
    if not trades:
        return "📭 No trade history"
    lines = ["*Recent Trades*\n"]
    for t in trades:
        emoji = "✅" if float(t.get("pnl", 0)) > 0 else ("🔄" if t.get("status") == "open" else "❌")
        lines.append(
            f"{emoji} {t.get('question','?')[:45]}\n"
            f"   {t.get('direction')} | PnL: ${float(t.get('pnl',0)):+.2f} | {t.get('status')}\n"
        )
    return "\n".join(lines)


def _fmt_whales() -> str:
    whales = get_whale_profiles()
    if not whales:
        return "🐳 No whales profiled yet"
    lines = ["*Top 5 Whales by PnL*\n"]
    for w in whales[:5]:
        cats = w.get("category_win_rates", {}) or {}
        cat_str = ", ".join(f"{k} {v:.0%}" for k, v in list(cats.items())[:3]) or "—"
        lines.append(
            f"🐳 *{w.get('username') or w.get('wallet','?')[:10]}*\n"
            f"   PnL: ${float(w.get('pnl',0)):,.0f} | Win: {float(w.get('win_rate',0)):.0%}\n"
            f"   Cats: {cat_str}\n"
            f"   Style: {w.get('conviction_signal','?')} | "
            f"Hold: {float(w.get('avg_hold_hours',0)):.0f}h | "
            f"{'closes early' if w.get('closes_early') else 'to resolution'}\n"
        )
    return "\n".join(lines)


def _fmt_committee(trade_id: str) -> str:
    report = get_committee_report(trade_id)
    if report is None and trade_id.isdigit():
        from db.models import get_conn
        conn = get_conn()
        row = conn.execute("SELECT position_id FROM signals WHERE id=?", (int(trade_id),)).fetchone()
        conn.close()
        if row and row["position_id"]:
            report = get_committee_report(row["position_id"])
    if report is None:
        return f"❓ No committee report for `{trade_id}`"

    wi   = report.get("whale_intent", {})
    eff  = report.get("efficiency", {})
    arch = report.get("archetype", {})
    cro  = report.get("cro", {})
    pf   = report.get("portfolio", {})
    sz   = report.get("sizing", {})
    flaws = cro.get("top_failure_modes", cro.get("fatal_flaws", []))
    return (
        f"*Committee Report* — {report.get('question','?')[:50]}\n"
        f"Verdict: *{report.get('verdict','?')}* | Conviction: {report.get('conviction','?')}/10\n\n"
        f"🐳 *Whale Intent*: {wi.get('intent','?')} | alpha {wi.get('alpha_confidence','?')}%\n"
        f"📊 *Efficiency*: {eff.get('efficiency_state','?')} | misprice {eff.get('mispricing_confidence','?')}%\n"
        f"🗂 *Archetype*: {arch.get('archetype','?')} | decay {arch.get('info_decay_hours','?')}h\n"
        f"🛡 *CRO*: {cro.get('rejection_risk_pct', cro.get('rejection_probability','?'))}% reject risk\n"
        f"   Liquidity: {cro.get('liquidity_risk','?')[:60]}\n"
        f"   Whale exit: {cro.get('whale_exit_risk','?')[:60]}\n"
        f"   Failure modes: {'; '.join(flaws[:3])}\n"
        f"📁 *Portfolio*: {pf.get('verdict','?')} | size adj {pf.get('size_adjustment','?')}x\n"
        f"💰 *Sizing*: kelly {sz.get('kelly_fraction','?')} | ${sz.get('dollar_amount','?')}\n"
    )


def _fmt_lessons() -> str:
    lessons = get_lessons(limit=10)
    if not lessons:
        return "🎓 No lessons recorded yet"
    lines = ["*Last 10 Post-Mortem Lessons*\n"]
    for l in lessons:
        helped = (l.get("reduced_losses", 0) or 0) > (l.get("ignored", 0) or 0)
        tag = "✅" if l.get("applied_count") and helped else ("⚠️" if l.get("ignored") else "•")
        lines.append(
            f"{tag} [{l.get('category','?')}] {l.get('lesson','')[:90]}\n"
            f"   → {l.get('future_rule','')[:80]}\n"
        )
    return "\n".join(lines)


def setup_handlers():
    if not _bot:
        return

    @_bot.message_handler(commands=["start", "status"])
    def cmd_status(message):
        _bot.reply_to(message, _fmt_stats())

    @_bot.message_handler(commands=["positions"])
    def cmd_positions(message):
        _bot.reply_to(message, _fmt_positions())

    @_bot.message_handler(commands=["history"])
    def cmd_history(message):
        _bot.reply_to(message, _fmt_history())

    @_bot.message_handler(commands=["pause"])
    def cmd_pause(message):
        global _paused
        _paused = True
        _bot.reply_to(message, "⏸ Bot PAUSED — no new trades will be placed")

    @_bot.message_handler(commands=["resume"])
    def cmd_resume(message):
        global _paused
        _paused = False
        _bot.reply_to(message, "▶️ Bot RESUMED")

    @_bot.message_handler(commands=["exit_all"])
    def cmd_exit_all(message):
        from scheduler.jobs import position_check_job
        _bot.reply_to(message, "🚨 Emergency exit — closing all positions...")
        position_check_job()
        _bot.reply_to(message, "✅ Exit orders placed")

    @_bot.message_handler(commands=["whales"])
    def cmd_whales(message):
        _bot.reply_to(message, _fmt_whales())

    @_bot.message_handler(commands=["committee"])
    def cmd_committee(message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            _bot.reply_to(message, "Usage: /committee <trade_id>")
            return
        _bot.reply_to(message, _fmt_committee(parts[1].strip()))

    @_bot.message_handler(commands=["lessons"])
    def cmd_lessons(message):
        _bot.reply_to(message, _fmt_lessons())

    @_bot.message_handler(commands=["help"])
    def cmd_help(message):
        _bot.reply_to(message, (
            "*PolyMind Commands*\n\n"
            "/status — bankroll, PnL, win rate\n"
            "/positions — open positions\n"
            "/history — last 10 trades\n"
            "/whales — top 5 whales by PnL\n"
            "/committee <id> — full 9-agent breakdown\n"
            "/lessons — last 10 post-mortem lessons\n"
            "/pause — pause trading\n"
            "/resume — resume trading\n"
            "/exit\\_all — emergency close all\n"
            "/help — this message"
        ))


def start_polling():
    if not _bot:
        logger.warning("Telegram bot not configured — skipping polling")
        return
    setup_handlers()
    thread = threading.Thread(target=_bot.infinity_polling, kwargs={"timeout": 30}, daemon=True)
    thread.start()
    logger.info("Telegram bot polling started")
