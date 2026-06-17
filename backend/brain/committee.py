"""
Investment Committee — 9-agent institutional decision pipeline.

Flow:
  1. Whale Intent Engine
  2. Market Efficiency Auditor
  3. Event Archetype Specialist
  4. Adversarial CRO Red Team
  5. Portfolio Risk Engine
  6. Confidence-Adjusted Kelly
  7. Investment Committee Vote (final)
"""
import logging
import requests
from datetime import datetime, timezone
from config import VIRTUALS_API_KEY, VIRTUALS_BASE_URL, COMMITTEE_MODELS, MODEL_OPUS
from brain.prompts import (
    WHALE_INTENT_SYSTEM, WHALE_INTENT_USER,
    EFFICIENCY_SYSTEM, EFFICIENCY_USER,
    ARCHETYPE_SYSTEM, ARCHETYPE_USER,
    CRO_SYSTEM, CRO_USER,
    PORTFOLIO_RISK_SYSTEM, PORTFOLIO_RISK_USER,
    SIZING_SYSTEM, SIZING_USER,
    COMMITTEE_SYSTEM, COMMITTEE_USER,
    POST_MORTEM_SYSTEM, POST_MORTEM_USER,
)

logger = logging.getLogger(__name__)

import re

STOPWORDS = {
    "will", "the", "a", "an", "to", "of", "in", "on", "by", "be", "is", "are",
    "and", "or", "for", "at", "this", "that", "before", "after", "than", "with",
    "does", "do", "have", "has", "any", "more", "less", "between", "during",
    "market", "yes", "no", "what", "when", "who", "how", "reach", "above", "below",
}


def derive_event_key(question: str, category: str = "other") -> str:
    """
    Cheap heuristic to group markets that share an underlying event.
    Two markets about "Trump 2024 election" should collide even if worded
    differently. We take the most salient content tokens.
    """
    q = (question or "").lower()
    tokens = re.findall(r"[a-z0-9]+", q)
    salient = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
    key_tokens = sorted(salient[:5])
    return f"{category}:{'_'.join(key_tokens)}" if key_tokens else category


def portfolio_hard_checks(trade: dict, market: dict, open_positions: list) -> dict:
    """
    Deterministic, non-LLM portfolio guardrails. Returns:
      {reject: bool, reason: str, dedup_count: int, yes_pct: float,
       same_day_count: int, correlated: bool}

    Rules:
      1. Event clustering — reject if >MAX_SAME_DAY_RESOLUTIONS open positions
         (incl. this one) resolve on the same calendar day.
      2. Directional concentration — reject if >MAX_YES_CONCENTRATION of open
         positions would be YES after adding this trade.
      3. Correlated markets — if this trade shares an event_key with an existing
         open position, the pair counts as ONE position for risk purposes
         (so we don't double-count exposure), and we flag the correlation.
    """
    from config import MAX_SAME_DAY_RESOLUTIONS, MAX_YES_CONCENTRATION

    direction = trade.get("direction", "YES")
    new_event_key = derive_event_key(market.get("question", ""), market.get("category", "other"))
    new_resolve_day = _resolve_day(market)

    # ── Correlated-market dedup ──
    event_keys = {}
    for p in open_positions:
        ek = p.get("event_key") or derive_event_key(p.get("question", ""), p.get("category", "other"))
        event_keys.setdefault(ek, []).append(p)
    correlated = new_event_key in event_keys

    # Distinct events = dedup count (correlated markets collapse to one).
    dedup_count = len(event_keys) + (0 if correlated else 1)

    # ── Same-day resolution clustering ──
    same_day = 1  # this trade
    if new_resolve_day:
        for p in open_positions:
            if p.get("resolve_date") and str(p["resolve_date"])[:10] == new_resolve_day:
                same_day += 1
    if same_day > MAX_SAME_DAY_RESOLUTIONS:
        return {
            "reject": True,
            "reason": f"Event clustering: {same_day} positions resolve on {new_resolve_day} "
                      f"(max {MAX_SAME_DAY_RESOLUTIONS})",
            "dedup_count": dedup_count, "same_day_count": same_day,
            "yes_pct": 0.0, "correlated": correlated, "event_key": new_event_key,
        }

    # ── Directional concentration (YES bias) ──
    # Count correlated markets once: skip positions sharing the new event_key
    # from the denominator to avoid double-penalizing.
    considered = [p for p in open_positions if (p.get("event_key") or
                  derive_event_key(p.get("question",""), p.get("category","other"))) != new_event_key]
    yes_count = sum(1 for p in considered if p.get("direction") == "YES")
    if direction == "YES":
        yes_count += 1
    total = len(considered) + 1
    yes_pct = yes_count / total if total else 0.0
    if total >= 4 and yes_pct > MAX_YES_CONCENTRATION:
        return {
            "reject": True,
            "reason": f"Directional concentration: {yes_pct:.0%} of {total} positions would be YES "
                      f"(max {MAX_YES_CONCENTRATION:.0%})",
            "dedup_count": dedup_count, "same_day_count": same_day,
            "yes_pct": yes_pct, "correlated": correlated, "event_key": new_event_key,
        }

    return {
        "reject": False, "reason": "Passed hard checks",
        "dedup_count": dedup_count, "same_day_count": same_day,
        "yes_pct": yes_pct, "correlated": correlated, "event_key": new_event_key,
    }


def _resolve_day(market: dict) -> str | None:
    expiry = market.get("endDate") or market.get("endDateIso") or market.get("resolve_date")
    if not expiry:
        return None
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
        return dt.date().isoformat()
    except Exception:
        return str(expiry)[:10] or None


HEADERS = {
    "Authorization": f"Bearer {VIRTUALS_API_KEY}",
    "Content-Type": "application/json",
}

# ── Tool schemas ──────────────────────────────────────────────

WHALE_INTENT_TOOL = {
    "name": "whale_intent_report",
    "description": "Report on whale's intent and alpha confidence",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent":              {"type": "string", "description": "Primary motive (e.g. Information advantage, Market making, Error...)"},
            "is_outlier":          {"type": "boolean"},
            "size_multiplier":     {"type": "number", "description": "This bet size / whale average size"},
            "alpha_confidence":    {"type": "number", "minimum": 0, "maximum": 100, "description": "% confidence this is real informational alpha"},
            "intent_score":        {"type": "integer", "minimum": 1, "maximum": 10},
            "reasoning":           {"type": "string", "maxLength": 300},
        },
        "required": ["intent", "is_outlier", "alpha_confidence", "intent_score", "reasoning"]
    }
}

EFFICIENCY_TOOL = {
    "name": "efficiency_report",
    "description": "Market efficiency and mispricing assessment",
    "input_schema": {
        "type": "object",
        "properties": {
            "efficiency_state":    {"type": "string", "enum": ["Efficient", "Slow-moving", "Underreacting", "Overreacting", "Misinformed"]},
            "efficiency_score":    {"type": "integer", "minimum": 1, "maximum": 10, "description": "1=highly inefficient (good), 10=fully efficient (no edge)"},
            "prob_low":            {"type": "number", "minimum": 0, "maximum": 1},
            "prob_base":           {"type": "number", "minimum": 0, "maximum": 1},
            "prob_high":           {"type": "number", "minimum": 0, "maximum": 1},
            "mispricing_confidence": {"type": "number", "minimum": 0, "maximum": 100},
            "edge_is_real":        {"type": "boolean"},
            "reasoning":           {"type": "string", "maxLength": 300},
        },
        "required": ["efficiency_state", "efficiency_score", "prob_base", "mispricing_confidence", "edge_is_real", "reasoning"]
    }
}

ARCHETYPE_TOOL = {
    "name": "archetype_report",
    "description": "Event archetype classification and behavioral patterns",
    "input_schema": {
        "type": "object",
        "properties": {
            "archetype":           {"type": "string"},
            "typical_overreaction": {"type": "string"},
            "typical_underreaction": {"type": "string"},
            "info_decay_hours":    {"type": "number", "description": "Hours until edge disappears"},
            "recommended_max_hold_days": {"type": "integer"},
            "historical_accuracy": {"type": "string"},
        },
        "required": ["archetype", "info_decay_hours", "recommended_max_hold_days"]
    }
}

CRO_TOOL = {
    "name": "cro_report",
    "description": "Chief Risk Officer adversarial review attacking liquidity, timing, whale-exit and correlation risk",
    "input_schema": {
        "type": "object",
        "properties": {
            "rejection_risk_pct":  {"type": "number", "minimum": 0, "maximum": 100, "description": "% probability the thesis is wrong"},
            "verdict":             {"type": "string", "enum": ["APPROVE", "CAUTION", "REJECT"]},
            "liquidity_risk":      {"type": "string", "description": "Concrete liquidity/exit risk assessment", "maxLength": 200},
            "event_timing_risk":   {"type": "string", "description": "Catalyst-already-priced / whipsaw risk", "maxLength": 200},
            "whale_exit_risk":     {"type": "string", "description": "Risk the followed whale dumps / we are exit liquidity", "maxLength": 200},
            "correlation_risk":    {"type": "string", "description": "Overlap with existing open positions", "maxLength": 200},
            "top_failure_modes":   {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3, "description": "Top 3 concrete ways this loses money"},
            "reasoning":           {"type": "string", "maxLength": 400},
        },
        "required": ["rejection_risk_pct", "verdict", "liquidity_risk",
                     "event_timing_risk", "whale_exit_risk", "correlation_risk",
                     "top_failure_modes", "reasoning"]
    }
}

PORTFOLIO_RISK_TOOL = {
    "name": "portfolio_risk_report",
    "description": "Portfolio-level risk assessment",
    "input_schema": {
        "type": "object",
        "properties": {
            "diversification_score": {"type": "integer", "minimum": 1, "maximum": 10, "description": "10=perfectly diversified"},
            "increases_fragility": {"type": "boolean"},
            "verdict":             {"type": "string", "enum": ["Accept", "Reduce", "Reject"]},
            "size_adjustment":     {"type": "number", "description": "Multiply recommended size by this (0.5 = halve it, 1.0 = keep, 0 = reject)"},
            "reasoning":           {"type": "string", "maxLength": 300},
        },
        "required": ["diversification_score", "increases_fragility", "verdict", "size_adjustment", "reasoning"]
    }
}

SIZING_TOOL = {
    "name": "sizing_report",
    "description": "Confidence-adjusted position sizing",
    "input_schema": {
        "type": "object",
        "properties": {
            "kelly_fraction":      {"type": "number", "minimum": 0, "maximum": 1},
            "allocation_pct":      {"type": "number", "minimum": 0, "maximum": 10},
            "dollar_amount":       {"type": "number"},
            "worst_case_drawdown": {"type": "number"},
            "reasoning":           {"type": "string", "maxLength": 300},
        },
        "required": ["kelly_fraction", "allocation_pct", "dollar_amount", "reasoning"]
    }
}

COMMITTEE_TOOL = {
    "name": "committee_verdict",
    "description": "Final Investment Committee decision",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict":             {"type": "string", "enum": ["APPROVE", "WATCH", "REJECT"]},
            "conviction":          {"type": "integer", "minimum": 1, "maximum": 10},
            "my_probability":      {"type": "number", "minimum": 0, "maximum": 1},
            "edge":                {"type": "number"},
            "direction":           {"type": "string", "enum": ["YES", "NO", "SKIP"]},
            "capital_allocation":  {"type": "number", "description": "Final dollar amount to bet"},
            "key_risks":           {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "reasoning":           {"type": "string", "maxLength": 500},
        },
        "required": ["verdict", "conviction", "my_probability", "direction", "capital_allocation", "reasoning"]
    }
}

POST_MORTEM_TOOL = {
    "name": "post_mortem_report",
    "description": "Structured post-trade learning",
    "input_schema": {
        "type": "object",
        "properties": {
            "edge_was_real":       {"type": "boolean"},
            "thesis_correct":      {"type": "boolean"},
            "timing_quality":      {"type": "string", "enum": ["Excellent", "Good", "Poor", "Bad"]},
            "lessons":             {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "future_rules":        {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "prompt_adjustments":  {"type": "string", "maxLength": 400},
        },
        "required": ["edge_was_real", "thesis_correct", "lessons", "future_rules"]
    }
}


# ── Core API caller ───────────────────────────────────────────

def _call(system: str, user: str, tool: dict, model: str | None = None) -> dict | None:
    import json
    payload = {
        "model": model or MODEL_OPUS,
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "tools": [tool],
    }
    try:
        r = requests.post(
            f"{VIRTUALS_BASE_URL}/chat/completions",
            headers=HEADERS,
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        resp = r.json()
        choices = resp.get("choices", [])
        if not choices:
            return None
        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
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
    except Exception as e:
        logger.error(f"Committee API call failed: {e}")
        return None


# ── Individual agents ─────────────────────────────────────────

def run_whale_intent(trade: dict, profile: dict) -> dict:
    category = trade.get("category", "other")
    cat_rates = profile.get("category_win_rates", {}) or {}
    this_cat_rate = cat_rates.get(category)
    this_cat_str = f"{this_cat_rate:.0%}" if isinstance(this_cat_rate, (int, float)) else "no history"
    user = WHALE_INTENT_USER.format(
        whale_username   = trade.get("whale_username", "Unknown"),
        whale_pnl        = trade.get("whale_pnl", 0),
        whale_win_rate   = trade.get("whale_win_rate", 0),
        typical_categories = ", ".join(profile.get("top_categories", ["Unknown"])),
        avg_bet_size     = profile.get("avg_bet_size", 100),
        recent_streak    = profile.get("recent_streak", "Unknown"),
        category_win_rates = ", ".join(f"{k}:{v:.0%}" for k, v in cat_rates.items()) or "none",
        category_win_rate = this_cat_str,
        avg_hold_hours   = profile.get("avg_hold_hours", 0),
        exit_behavior    = "closes early" if profile.get("closes_early") else "holds long",
        hold_to_resolution_pct = f"{profile.get('hold_to_resolution_pct', 0):.0%}",
        conviction_signal = profile.get("conviction_signal", "unknown"),
        avg_tranches     = profile.get("avg_tranches", 1),
        question         = trade.get("question", ""),
        direction        = trade.get("direction", "YES"),
        entry_price      = float(trade.get("entry_price", 0.5)) * 100,
        whale_size       = float(trade.get("whale_size", 0)),
        category         = category,
        trade_age_seconds = trade.get("trade_age_seconds", 0),
    )
    result = _call(WHALE_INTENT_SYSTEM, user, WHALE_INTENT_TOOL, COMMITTEE_MODELS["whale_intent"])
    return result or {"intent": "Unknown", "alpha_confidence": 40, "intent_score": 4, "reasoning": "API unavailable", "is_outlier": False}


def run_efficiency_audit(market: dict, current_price: float) -> dict:
    user = EFFICIENCY_USER.format(
        question       = market.get("question", ""),
        yes_price      = current_price * 100,
        price_24h      = float(market.get("lastPrice24H", current_price) or current_price) * 100,
        price_7d       = float(market.get("lastPrice1w", current_price) or current_price) * 100,
        volume_today   = float(market.get("volume24hr", 0) or 0),
        volume_7d_avg  = float(market.get("volume", 0) or 0) / 7,
        category       = market.get("category", "other"),
        days_to_expiry = market.get("days_to_expiry", 14),
    )
    result = _call(EFFICIENCY_SYSTEM, user, EFFICIENCY_TOOL, COMMITTEE_MODELS["efficiency"])
    return result or {"efficiency_state": "Unknown", "efficiency_score": 5, "prob_base": current_price, "mispricing_confidence": 50, "edge_is_real": True, "reasoning": "API unavailable"}


def run_archetype(market: dict, current_price: float) -> dict:
    user = ARCHETYPE_USER.format(
        question       = market.get("question", ""),
        category       = market.get("category", "other"),
        yes_price      = current_price * 100,
        days_to_expiry = market.get("days_to_expiry", 14),
    )
    result = _call(ARCHETYPE_SYSTEM, user, ARCHETYPE_TOOL, COMMITTEE_MODELS["archetype"])
    return result or {"archetype": "Other", "info_decay_hours": 24, "recommended_max_hold_days": 14}


def run_cro(trade: dict, market: dict, current_price: float, analyst_score: int,
            edge: float, reasoning: str, open_positions: list | None = None,
            whale_profile: dict | None = None) -> dict:
    open_positions = open_positions or []
    whale_profile  = whale_profile or {}
    pos_summary = "\n".join(
        f"  - {p.get('direction')} {p.get('question','?')[:45]} | {p.get('category','?')}"
        for p in open_positions[:8]
    ) or "  No open positions"
    exit_profile = (
        f"{whale_profile.get('conviction_signal','unknown')}, "
        f"{'closes early' if whale_profile.get('closes_early') else 'holds to resolution'}, "
        f"avg hold {whale_profile.get('avg_hold_hours', 0)}h"
    )
    user = CRO_USER.format(
        question       = market.get("question", ""),
        category       = market.get("category", "other"),
        direction      = trade.get("direction", "YES"),
        yes_price      = current_price * 100,
        analyst_score  = analyst_score,
        whale_username = trade.get("whale_username", "Unknown"),
        whale_pnl      = trade.get("whale_pnl", 0),
        whale_exit_profile = exit_profile,
        edge           = edge,
        volume         = float(market.get("volume", 0) or 0),
        days_to_expiry = market.get("days_to_expiry", 14),
        open_positions_summary = pos_summary,
        reasoning      = reasoning,
    )
    result = _call(CRO_SYSTEM, user, CRO_TOOL, COMMITTEE_MODELS["cro"])
    if not result:
        result = {
            "rejection_risk_pct": 50, "verdict": "CAUTION",
            "liquidity_risk": "unknown", "event_timing_risk": "unknown",
            "whale_exit_risk": "unknown", "correlation_risk": "unknown",
            "top_failure_modes": ["API unavailable"],
            "reasoning": "Could not complete CRO review",
        }
    # Backward-compat aliases used elsewhere in the pipeline / notifications.
    result["rejection_probability"] = result.get("rejection_risk_pct", result.get("rejection_probability", 50))
    result["fatal_flaws"] = result.get("top_failure_modes", result.get("fatal_flaws", []))
    return result


def run_portfolio_risk(trade: dict, market: dict, open_positions: list) -> dict:
    pos_summary = "\n".join(
        f"  - {p.get('direction')} {p.get('question','?')[:40]} | ${p.get('size',0):.2f} | {p.get('category','?')}"
        for p in open_positions[:8]
    ) or "  No open positions"
    total_exposure = sum(float(p.get("size", 0)) for p in open_positions)
    cats = {}
    for p in open_positions:
        c = p.get("category", "other")
        cats[c] = cats.get(c, 0) + 1
    yes_count = sum(1 for p in open_positions if p.get("direction") == "YES")
    no_count  = len(open_positions) - yes_count
    avg_exp   = 14.0

    user = PORTFOLIO_RISK_USER.format(
        direction          = trade.get("direction", "YES"),
        question           = market.get("question", ""),
        category           = market.get("category", "other"),
        days_to_expiry     = market.get("days_to_expiry", 14),
        open_count         = len(open_positions),
        positions_summary  = pos_summary,
        total_exposure     = total_exposure,
        category_breakdown = str(cats),
        yes_count          = yes_count,
        no_count           = no_count,
        avg_expiry         = avg_exp,
    )
    result = _call(PORTFOLIO_RISK_SYSTEM, user, PORTFOLIO_RISK_TOOL, COMMITTEE_MODELS["portfolio"])
    return result or {"diversification_score": 5, "increases_fragility": False, "verdict": "Accept", "size_adjustment": 1.0, "reasoning": "API unavailable"}


def run_sizing(bankroll: float, my_prob: float, market_price: float,
               whale_alpha: float, efficiency_score: int,
               mispricing_pct: float, archetype: str,
               cro_rejection: float, open_count: int,
               correlated_exposure: float) -> dict:
    edge = my_prob - market_price
    user = SIZING_USER.format(
        bankroll            = bankroll,
        my_prob             = my_prob,
        market_price        = market_price,
        edge                = edge,
        whale_alpha_pct     = whale_alpha,
        efficiency_score    = efficiency_score,
        mispricing_pct      = mispricing_pct,
        archetype           = archetype,
        cro_rejection_pct   = cro_rejection,
        open_count          = open_count,
        correlated_exposure = correlated_exposure,
    )
    result = _call(SIZING_SYSTEM, user, SIZING_TOOL, COMMITTEE_MODELS["sizing"])
    return result or {"kelly_fraction": 0.25, "allocation_pct": 2.5, "dollar_amount": bankroll * 0.025, "reasoning": "Default conservative sizing"}


def _format_lessons(lessons: list) -> str:
    if not lessons:
        return "No prior lessons for this category yet."
    out = []
    for l in lessons[:5]:
        tag = "✅ helped" if l.get("reduced_losses", 0) > l.get("ignored", 0) else (
            "⚠️ ignored" if l.get("ignored", 0) > 0 else "• new")
        out.append(f"  [{tag}] {l.get('lesson','')} → rule: {l.get('future_rule','')}")
    return "\n".join(out)


def run_final_committee(trade: dict, market: dict, current_price: float,
                        whale_intent: dict, efficiency: dict,
                        archetype: dict, cro: dict, portfolio: dict,
                        lessons: list | None = None) -> dict:
    lessons_block = _format_lessons(lessons or [])
    user = COMMITTEE_USER.format(
        prior_lessons     = lessons_block,
        question          = market.get("question", ""),
        yes_price         = current_price * 100,
        category          = market.get("category", "other"),
        volume            = float(market.get("volume", 0) or 0),
        days_to_expiry    = market.get("days_to_expiry", 14),
        whale_username    = trade.get("whale_username", "Unknown"),
        whale_pnl         = trade.get("whale_pnl", 0),
        whale_win_rate    = trade.get("whale_win_rate", 0),
        direction         = trade.get("direction", "YES"),
        entry_price       = float(trade.get("entry_price", current_price)) * 100,
        whale_size        = float(trade.get("whale_size", 0)),
        whale_intent_summary  = f"Intent: {whale_intent.get('intent')} | Alpha confidence: {whale_intent.get('alpha_confidence')}% | {whale_intent.get('reasoning','')}",
        efficiency_summary    = f"State: {efficiency.get('efficiency_state')} | Mispricing confidence: {efficiency.get('mispricing_confidence')}% | Prob range: {efficiency.get('prob_low',0):.2f}–{efficiency.get('prob_high',1):.2f}",
        cro_summary           = f"Rejection prob: {cro.get('rejection_probability')}% | Verdict: {cro.get('verdict')} | Flaws: {'; '.join(cro.get('fatal_flaws',[])[:2])}",
        portfolio_summary     = f"Fragility: {'↑' if portfolio.get('increases_fragility') else '↓'} | Verdict: {portfolio.get('verdict')} | Size adj: {portfolio.get('size_adjustment',1):.1f}x",
    )
    result = _call(COMMITTEE_SYSTEM, user, COMMITTEE_TOOL, COMMITTEE_MODELS["committee"])
    return result or {"verdict": "REJECT", "conviction": 0, "my_probability": current_price, "direction": "SKIP", "capital_allocation": 0, "reasoning": "Committee API unavailable"}


# ── Stage-1 fan-out + archetype cache ─────────────────────────

# Archetype barely varies for a given (category, archetype-of-question); cache it
# so repeat markets in the same family skip the (Haiku) call entirely.
_archetype_cache: dict[str, dict] = {}


def _cached_archetype(market: dict, current_price: float) -> dict:
    key = derive_event_key(market.get("question", ""), market.get("category", "other"))
    if key in _archetype_cache:
        return _archetype_cache[key]
    result = run_archetype(market, current_price)
    # Only cache real results, never the API-unavailable fallback.
    if result and result.get("archetype") not in (None, "Other"):
        _archetype_cache[key] = result
    return result


def _run_stage1(trade: dict, market: dict, current_price: float,
                whale_profile: dict) -> tuple[dict, dict, dict]:
    """
    Run the three independent first-stage analysts. Concurrently when
    COMMITTEE_PARALLEL is on (default), else sequentially. Each agent already
    has its own try/except fallback, so a failure degrades to its fallback dict
    rather than crashing the pool.
    """
    from config import COMMITTEE_PARALLEL
    tasks = {
        "whale_intent": lambda: run_whale_intent(trade, whale_profile),
        "efficiency":   lambda: run_efficiency_audit(market, current_price),
        "archetype":    lambda: _cached_archetype(market, current_price),
    }
    if not COMMITTEE_PARALLEL:
        return tasks["whale_intent"](), tasks["efficiency"](), tasks["archetype"]()

    from concurrent.futures import ThreadPoolExecutor
    results: dict = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {k: ex.submit(fn) for k, fn in tasks.items()}
        for k, fut in futures.items():
            try:
                results[k] = fut.result()
            except Exception as e:
                logger.error(f"Stage-1 agent {k} failed: {e}")
                results[k] = None
    # Apply the same fallbacks the sequential runners use if anything came back None.
    return (
        results.get("whale_intent") or {"intent": "Unknown", "alpha_confidence": 40, "intent_score": 4, "reasoning": "stage1 error", "is_outlier": False},
        results.get("efficiency") or {"efficiency_state": "Unknown", "efficiency_score": 5, "prob_base": current_price, "mispricing_confidence": 50, "edge_is_real": True, "reasoning": "stage1 error"},
        results.get("archetype") or {"archetype": "Other", "info_decay_hours": 24, "recommended_max_hold_days": 14},
    )


# ── Main entry point ──────────────────────────────────────────

def run_committee(trade: dict, market: dict, current_price: float,
                  whale_profile: dict, open_positions: list,
                  bankroll: float, consensus: dict | None = None,
                  lessons: list | None = None) -> dict:
    """
    Run the full 9-agent institutional decision pipeline.
    Returns final committee verdict dict.

    `consensus` (optional): {whale_count, consensus_score, whales, aligned}
    from the multi-whale consensus filter. The score is fed to the committee
    and sizing agents as an additional conviction signal.

    `lessons` (optional): recent post-mortem lessons for this event category,
    injected into the final committee prompt. Fetched automatically if None.
    """
    consensus = consensus or {"whale_count": 1, "consensus_score": 0.0, "whales": []}
    consensus_score = float(consensus.get("consensus_score", 0.0))

    if lessons is None:
        try:
            from db.models import get_recent_lessons_for_category
            lessons = get_recent_lessons_for_category(market.get("category", "other"), limit=5)
        except Exception:
            lessons = []
    logger.info(
        f"Committee convening for: {market.get('question','?')[:60]} "
        f"(consensus {consensus.get('whale_count',1)} whales, score {consensus_score:.2f})"
    )

    # ── Gate 0: deterministic portfolio guardrails (FREE — run before any LLM) ──
    # Cheapest possible early-exit: kill a structurally-doomed trade before we
    # spend a single token on it.
    hard = portfolio_hard_checks(trade, market, open_positions)
    if hard.get("reject"):
        logger.info(f"  PORTFOLIO HARD-REJECT (pre-LLM): {hard.get('reason')}")
        return {
            "verdict": "REJECT", "conviction": 0,
            "direction": "SKIP", "capital_allocation": 0,
            "my_probability": current_price,
            "reasoning": f"Portfolio guardrail: {hard.get('reason')}",
            "consensus_score": consensus_score,
            "committee_reports": {
                "portfolio": {"verdict": "Reject", "hard_checks": hard,
                              "reasoning": hard.get("reason")},
            },
        }

    # ── Stage 1: the three independent analysts run concurrently ──
    # Whale-intent, efficiency and archetype have no inter-dependencies, so we
    # fan them out to cut decision latency (critical when racing a whale).
    logger.info("  [1-3/6] Whale intent + efficiency + archetype (parallel)...")
    whale_intent, efficiency, archetype_result = _run_stage1(
        trade, market, current_price, whale_profile,
    )

    # ── Stage 2: CRO Red Team (depends on intent + efficiency) ──
    logger.info("  [4/6] CRO adversarial review...")
    cro = run_cro(
        trade, market, current_price,
        analyst_score = whale_intent.get("intent_score", 5),
        edge          = efficiency.get("prob_base", current_price) - current_price,
        reasoning     = whale_intent.get("reasoning", ""),
        open_positions = open_positions,
        whale_profile  = whale_profile,
    )

    # Auto-reject if CRO rejection probability > 40%
    if cro.get("rejection_probability", 0) > 40:
        logger.info(f"  CRO VETO: rejection_probability={cro.get('rejection_probability')}% — REJECTED")
        return {
            "verdict": "REJECT", "conviction": 0,
            "direction": "SKIP", "capital_allocation": 0,
            "my_probability": current_price,
            "reasoning": f"CRO veto: {'; '.join(cro.get('fatal_flaws', [])[:2])}",
            "committee_reports": {"whale_intent": whale_intent, "efficiency": efficiency, "archetype": archetype_result, "cro": cro},
        }

    # Agent 7: Portfolio Risk (LLM)
    logger.info("  [5/6] Portfolio risk assessment...")
    portfolio = run_portfolio_risk(trade, market, open_positions)
    portfolio["hard_checks"] = hard
    if hard.get("correlated"):
        logger.info(f"  Correlated market detected (event_key={hard.get('event_key')}) — counts as 1 position")

    if portfolio.get("verdict") == "Reject":
        logger.info("  Portfolio risk manager REJECTED")
        return {
            "verdict": "REJECT", "conviction": 0,
            "direction": "SKIP", "capital_allocation": 0,
            "my_probability": current_price,
            "reasoning": f"Portfolio risk: {portfolio.get('reasoning','')}",
            "committee_reports": {"whale_intent": whale_intent, "efficiency": efficiency, "archetype": archetype_result, "cro": cro, "portfolio": portfolio},
        }

    # Agent 6: Sizing
    logger.info("  [6/6] Position sizing...")
    correlated = sum(float(p.get("size", 0)) for p in open_positions if p.get("category") == market.get("category"))
    sizing = run_sizing(
        bankroll            = bankroll,
        my_prob             = efficiency.get("prob_base", current_price),
        market_price        = current_price,
        whale_alpha         = whale_intent.get("alpha_confidence", 50),
        efficiency_score    = efficiency.get("efficiency_score", 5),
        mispricing_pct      = efficiency.get("mispricing_confidence", 50),
        archetype           = archetype_result.get("archetype", "Other"),
        cro_rejection       = cro.get("rejection_probability", 25),
        open_count          = len(open_positions),
        correlated_exposure = correlated,
    )

    # Apply portfolio size adjustment
    size_adj = portfolio.get("size_adjustment", 1.0)
    final_size = sizing.get("dollar_amount", 2.0) * size_adj

    # Consensus boost: multiple aligned whales raise conviction and size.
    # Up to +40% size at a perfect consensus score.
    consensus_mult = 1.0 + 0.4 * consensus_score
    final_size *= consensus_mult

    # Agent 1 (final): Investment Committee vote
    logger.info("  [Committee] Final vote...")
    verdict = run_final_committee(trade, market, current_price, whale_intent, efficiency, archetype_result, cro, portfolio, lessons)
    verdict["capital_allocation"] = final_size
    verdict["consensus_score"]    = consensus_score
    verdict["consensus_whales"]   = consensus.get("whale_count", 1)

    # A strong consensus nudges conviction up by 1 (capped at 10).
    if consensus_score >= 0.6 and verdict.get("conviction"):
        verdict["conviction"] = min(10, int(verdict["conviction"]) + 1)

    verdict["committee_reports"] = {
        "whale_intent":  whale_intent,
        "efficiency":    efficiency,
        "archetype":     archetype_result,
        "cro":           cro,
        "portfolio":     portfolio,
        "sizing":        sizing,
        "consensus":     consensus,
    }

    logger.info(
        f"  VERDICT: {verdict.get('verdict')} | "
        f"Conviction: {verdict.get('conviction')}/10 | "
        f"Allocation: ${final_size:.2f}"
    )
    return verdict


def run_post_mortem(position: dict) -> dict:
    user = POST_MORTEM_USER.format(
        question      = position.get("question", ""),
        direction     = position.get("direction", ""),
        entry_price   = float(position.get("entry_price", 0)),
        exit_price    = float(position.get("exit_price", 0)),
        exit_reason   = position.get("exit_reason", "unknown"),
        pnl           = float(position.get("pnl", 0)),
        hold_days     = position.get("hold_days", 0),
        reasoning     = position.get("reasoning", ""),
        claude_score  = position.get("claude_score", 0),
        whale_username = position.get("whale_name", "Unknown"),
    )
    result = _call(POST_MORTEM_SYSTEM, user, POST_MORTEM_TOOL, COMMITTEE_MODELS["post_mortem"])
    return result or {"edge_was_real": False, "thesis_correct": False, "lessons": ["API unavailable"], "future_rules": []}
