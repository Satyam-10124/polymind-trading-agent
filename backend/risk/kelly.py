import logging
from config import BANKROLL, MAX_BET_PCT, KELLY_FRACTION

logger = logging.getLogger(__name__)


def kelly_bet(bankroll: float, my_prob: float, market_price: float) -> float:
    if market_price <= 0 or market_price >= 1:
        return 0.0
    edge = my_prob - market_price
    if edge <= 0:
        return 0.0
    odds   = (1 - market_price) / market_price
    kelly  = edge / (1 / odds)
    half_k = kelly * KELLY_FRACTION
    max_bet = bankroll * MAX_BET_PCT
    bet = min(bankroll * half_k, max_bet)
    bet = max(bet, 1.0)
    logger.info(
        f"Kelly: prob={my_prob:.2f} price={market_price:.2f} "
        f"edge={edge:.3f} kelly={kelly:.3f} bet=${bet:.2f}"
    )
    return round(bet, 2)


def get_current_bankroll(positions_value: float = 0.0, wallet_balance: float = BANKROLL) -> float:
    return wallet_balance + positions_value
