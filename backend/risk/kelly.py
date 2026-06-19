"""
Enhanced Kelly sizing.

- Dynamic Kelly fraction based on the rolling win rate of the last 20 closed
  trades (post-mortem outcomes):
      win_rate < 55%        -> 0.30x  (defensive)
      55% <= win_rate <= 65% -> 0.50x  (standard half-Kelly)
      win_rate > 65%        -> 0.70x  (aggressive)
- Drawdown circuit breaker: if current drawdown from peak bankroll > 15%,
  cut all new position sizes by 50%.
- Every sizing decision is logged with a full calculation breakdown to SQLite
  (sizing_decisions table).
"""
import logging
from config import BANKROLL, MAX_BET_PCT, KELLY_FRACTION, DRAWDOWN_BREAKER_PCT, PEAK_BANKROLL

logger = logging.getLogger(__name__)


def dynamic_kelly_fraction(recent_outcomes: list[int]) -> tuple[float, float]:
    """
    Returns (kelly_fraction, win_rate) from the last 20 outcomes (1=win, 0=loss).
    Falls back to the configured KELLY_FRACTION when we have too little data.
    """
    sample = recent_outcomes[:20]
    if len(sample) < 5:
        return KELLY_FRACTION, (sum(sample) / len(sample) if sample else 0.0)
    win_rate = sum(sample) / len(sample)
    if win_rate < 0.55:
        frac = 0.30
    elif win_rate <= 0.65:
        frac = 0.50
    else:
        frac = 0.70
    return frac, win_rate


def current_drawdown(bankroll: float, peak: float | None = None) -> float:
    """Fractional drawdown from peak (0.0 = at peak, 0.20 = 20% below peak)."""
    peak = max(peak or PEAK_BANKROLL, bankroll)
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - bankroll) / peak)


def kelly_bet(bankroll: float, my_prob: float, market_price: float,
              recent_outcomes: list[int] | None = None,
              peak_bankroll: float | None = None,
              position_id: str | None = None,
              question: str | None = None,
              persist: bool = True) -> float:
    if market_price <= 0 or market_price >= 1:
        return 0.0
    edge = my_prob - market_price
    if edge <= 0:
        return 0.0

    odds      = (1 - market_price) / market_price
    raw_kelly = edge / (1 - market_price)

    recent_outcomes = recent_outcomes or []
    frac, win_rate  = dynamic_kelly_fraction(recent_outcomes)

    adj_kelly = raw_kelly * frac
    max_bet   = bankroll * MAX_BET_PCT
    bet       = min(bankroll * adj_kelly, max_bet)

    # Drawdown circuit breaker.
    dd = current_drawdown(bankroll, peak_bankroll)
    breaker_tripped = dd > DRAWDOWN_BREAKER_PCT
    if breaker_tripped:
        bet *= 0.5

    bet = max(bet, 1.0)
    bet = round(bet, 2)

    breakdown = {
        "edge":            round(edge, 4),
        "odds":            round(odds, 4),
        "raw_kelly":       round(raw_kelly, 4),
        "kelly_fraction":  frac,
        "recent_win_rate": round(win_rate, 3),
        "sample_size":     len(recent_outcomes[:20]),
        "adj_kelly":       round(adj_kelly, 4),
        "max_bet_cap":     round(max_bet, 2),
        "drawdown_pct":    round(dd, 4),
        "circuit_breaker": breaker_tripped,
        "final_bet":       bet,
    }
    logger.info(
        f"Kelly: prob={my_prob:.2f} price={market_price:.2f} edge={edge:.3f} "
        f"raw_kelly={raw_kelly:.3f} frac={frac:.2f} (wr={win_rate:.0%}) "
        f"dd={dd:.1%}{' BREAKER' if breaker_tripped else ''} bet=${bet:.2f}"
    )

    if persist:
        try:
            from db.models import save_sizing_decision
            save_sizing_decision({
                "position_id":     position_id,
                "question":        question,
                "bankroll":        bankroll,
                "my_prob":         my_prob,
                "market_price":    market_price,
                "edge":            edge,
                "raw_kelly":       raw_kelly,
                "recent_win_rate": win_rate,
                "kelly_fraction":  frac,
                "drawdown_pct":    dd,
                "circuit_breaker": breaker_tripped,
                "final_bet":       bet,
                "breakdown":       breakdown,
            })
        except Exception as e:
            logger.error(f"save_sizing_decision failed: {e}")

    return bet


def get_current_bankroll(positions_value: float = 0.0, wallet_balance: float = BANKROLL) -> float:
    return wallet_balance + positions_value
