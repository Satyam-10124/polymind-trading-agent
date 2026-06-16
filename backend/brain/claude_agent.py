import requests
import logging
from datetime import datetime, timezone
from config import VIRTUALS_API_KEY, VIRTUALS_BASE_URL, MIN_EDGE, MIN_CLAUDE_SCORE
from brain.prompts import (
    WHALE_COPY_SYSTEM, WHALE_COPY_USER,
    MARKET_SCAN_SYSTEM, MARKET_SCAN_USER,
    DAILY_REPORT_SYSTEM, DAILY_REPORT_USER,
    TRADE_DECISION_TOOL,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "Authorization": f"Bearer {VIRTUALS_API_KEY}",
    "Content-Type": "application/json",
}


def _call_virtuals(system: str, user: str, tools: list = None, model: str = "claude-opus-4-5") -> dict | None:
    payload = {
        "model": model,
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if tools:
        payload["tools"] = tools

    try:
        r = requests.post(
            f"{VIRTUALS_BASE_URL}/chat/completions",
            headers=HEADERS,
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Virtuals API call failed: {e}")
        return None


def _extract_tool_result(response: dict) -> dict | None:
    if not response:
        return None
    choices = response.get("choices", [])
    if not choices:
        return None
    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls", [])
    if tool_calls:
        import json
        args = tool_calls[0].get("function", {}).get("arguments", "{}")
        try:
            return json.loads(args)
        except Exception:
            return None
    content = message.get("content", "")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return block.get("input", {})
    return None


def analyse_whale_trade(trade: dict, market: dict, current_price: float) -> dict | None:
    from datetime import datetime, timezone
    expiry = market.get("endDate") or market.get("endDateIso", "")
    try:
        exp_dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
        days_to_expiry = max(0, (exp_dt - datetime.now(timezone.utc)).days)
    except Exception:
        days_to_expiry = 14

    entry_price = float(trade.get("price", current_price) or current_price)
    side        = trade.get("side", trade.get("outcome", "YES")).upper()
    size        = float(trade.get("usdcSize", trade.get("amount", 0)) or 0)
    question    = market.get("question", trade.get("title", "Unknown market"))
    category    = market.get("category", "other")
    volume      = float(market.get("volume", 0) or 0)

    user_msg = WHALE_COPY_USER.format(
        whale_username  = trade.get("whale_username", "Unknown"),
        whale_pnl       = trade.get("whale_pnl", 0),
        question        = question,
        side            = side,
        entry_price     = entry_price * 100,
        whale_size      = size,
        current_price   = current_price * 100,
        category        = category,
        days_to_expiry  = days_to_expiry,
        market_volume   = volume,
    )

    response = _call_virtuals(WHALE_COPY_SYSTEM, user_msg, tools=[TRADE_DECISION_TOOL])
    result   = _extract_tool_result(response)
    if result:
        result["question"]       = question
        result["market_id"]      = market.get("conditionId") or market.get("id")
        result["token_id"]       = market.get("clobTokenIds", [None])[0] if side == "YES" else market.get("clobTokenIds", [None, None])[1]
        result["current_price"]  = current_price
        result["side"]           = side
    return result


def analyse_market_independently(market: dict, current_price: float) -> dict | None:
    expiry = market.get("endDate") or market.get("endDateIso", "")
    try:
        exp_dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
        days_to_expiry = max(0, (exp_dt - datetime.now(timezone.utc)).days)
    except Exception:
        days_to_expiry = 14

    price_24h = float(market.get("lastPrice24H", current_price) or current_price)
    user_msg  = MARKET_SCAN_USER.format(
        question        = market.get("question", ""),
        yes_price       = current_price * 100,
        volume          = float(market.get("volume", 0) or 0),
        days_to_expiry  = days_to_expiry,
        category        = market.get("category", "other"),
        price_24h       = price_24h * 100,
    )

    response = _call_virtuals(MARKET_SCAN_SYSTEM, user_msg, tools=[TRADE_DECISION_TOOL])
    result   = _extract_tool_result(response)
    if result:
        result["question"]   = market.get("question", "")
        result["market_id"]  = market.get("conditionId") or market.get("id")
        result["token_id"]   = market.get("clobTokenIds", [None])[0]
        result["current_price"] = current_price
    return result


def should_trade(decision: dict) -> bool:
    if not decision:
        return False
    if decision.get("direction") == "SKIP":
        return False
    if decision.get("score", 0) < MIN_CLAUDE_SCORE:
        return False
    if abs(decision.get("edge", 0)) < MIN_EDGE:
        return False
    return True


def generate_daily_report(stats: dict, trades: list) -> str:
    trade_log = "\n".join(
        f"  {'✅' if t.get('pnl',0)>0 else '❌'} {t.get('question','?')[:50]} "
        f"→ {t.get('direction','?')} @ {t.get('entry_price',0):.2f}¢ "
        f"→ PnL: ${t.get('pnl',0):+.2f}"
        for t in trades[-10:]
    ) or "  No trades today"

    user_msg = DAILY_REPORT_USER.format(
        date             = datetime.now().strftime("%Y-%m-%d"),
        start_bankroll   = stats.get("start_bankroll", 50),
        current_bankroll = stats.get("current_bankroll", 50),
        daily_pnl        = stats.get("daily_pnl", 0),
        trades_count     = stats.get("trades_count", 0),
        win_rate         = stats.get("win_rate", 0),
        trade_log        = trade_log,
    )
    response = _call_virtuals(DAILY_REPORT_SYSTEM, user_msg, model="claude-opus-4-5")
    if response:
        choices = response.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                return " ".join(b.get("text", "") for b in content if b.get("type") == "text")
            return str(content)
    return "Report generation failed."
