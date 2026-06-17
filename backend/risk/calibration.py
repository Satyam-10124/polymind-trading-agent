"""
Probability calibration.

The committee emits a stated probability (`my_probability`). Kelly is only optimal
when that number is the *true* probability — and LLMs are systematically
overconfident. This module measures that overconfidence against realized outcomes
and shrinks the stated probability toward the market price before sizing.

Two layers:
  1. Reliability curve — bucket predicted probability vs realized win frequency,
     so the dashboard / operator can SEE the miscalibration.
  2. `calibrate_probability()` — the production shrinkage applied before Kelly:
       - shrink toward the market price (markets are mostly efficient),
       - weighted by how much we trust the model in this probability band,
       - and by the consensus strength (more aligned whales -> trust the edge more),
       - then hard-cap the maximum edge claim at MAX_PROB_DEVIATION.

When there is too little history (< CALIBRATION_MIN_SAMPLES) we apply only the
deviation cap and a mild default shrink, never the data-driven factor.
"""
import logging
from config import (
    CALIBRATION_ENABLED, CALIBRATION_MIN_SAMPLES, MAX_PROB_DEVIATION, MIN_EDGE,
)

logger = logging.getLogger(__name__)

# Probability buckets for the reliability curve.
_BUCKETS = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5),
            (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]


def reliability_curve(samples: list[dict]) -> list[dict]:
    """
    samples: [{my_prob, win(0/1)}]. Returns one row per non-empty bucket:
      {bucket, predicted (avg predicted prob), realized (win freq), n}
    """
    out = []
    for lo, hi in _BUCKETS:
        in_bucket = [s for s in samples if lo <= s["my_prob"] < hi or (hi == 1.0 and s["my_prob"] == 1.0)]
        if not in_bucket:
            continue
        n = len(in_bucket)
        predicted = sum(s["my_prob"] for s in in_bucket) / n
        realized = sum(s["win"] for s in in_bucket) / n
        out.append({
            "bucket":    f"{int(lo*100)}-{int(hi*100)}%",
            "predicted": round(predicted, 3),
            "realized":  round(realized, 3),
            "n":         n,
        })
    return out


def overconfidence_factor(samples: list[dict]) -> float:
    """
    A single multiplicative shrink in (0, 1] applied to the model's *edge over 0.5*.
    1.0 = perfectly calibrated; lower = more overconfident.

    Computed as realized_winrate / predicted_winrate over samples where the model
    expressed an opinion (predicted away from 0.5). Bounded to [0.3, 1.0] so a small
    noisy sample can't invert the sign or wildly inflate confidence.
    """
    opinionated = [s for s in samples if abs(s["my_prob"] - 0.5) >= 0.05]
    if len(opinionated) < CALIBRATION_MIN_SAMPLES:
        return 1.0
    avg_pred = sum(s["my_prob"] for s in opinionated) / len(opinionated)
    avg_real = sum(s["win"] for s in opinionated) / len(opinionated)
    if avg_pred <= 0.5:
        return 1.0
    # How much of the claimed edge-over-coinflip actually materialised.
    pred_edge = avg_pred - 0.5
    real_edge = avg_real - 0.5
    if pred_edge <= 0:
        return 1.0
    factor = real_edge / pred_edge
    return max(0.3, min(1.0, factor))


def calibrate_probability(my_prob: float, market_price: float,
                          samples: list[dict] | None = None,
                          consensus_score: float = 0.0) -> dict:
    """
    Returns {calibrated_prob, raw_prob, factor, capped, reason}.

    The calibrated probability is the market price plus a shrunk, capped deviation:
        deviation     = my_prob - market_price
        trust         = overconfidence_factor (data) blended with consensus
        shrunk        = deviation * trust
        capped        = clamp(shrunk, ±MAX_PROB_DEVIATION)
        calibrated    = market_price + capped
    """
    samples = samples or []
    raw_dev = my_prob - market_price

    if not CALIBRATION_ENABLED:
        return {"calibrated_prob": my_prob, "raw_prob": my_prob,
                "factor": 1.0, "capped": False, "reason": "calibration disabled"}

    data_factor = overconfidence_factor(samples)
    # Consensus raises trust in the edge: 0 whales-aligned -> use data factor as-is;
    # strong consensus nudges trust up toward 1.0 (but never above).
    trust = min(1.0, data_factor + 0.3 * consensus_score * (1.0 - data_factor))

    shrunk = raw_dev * trust
    capped = False
    if shrunk > MAX_PROB_DEVIATION:
        shrunk = MAX_PROB_DEVIATION; capped = True
    elif shrunk < -MAX_PROB_DEVIATION:
        shrunk = -MAX_PROB_DEVIATION; capped = True

    calibrated = max(0.01, min(0.99, market_price + shrunk))

    n = len([s for s in samples if abs(s["my_prob"] - 0.5) >= 0.05])
    reason = (
        f"trust={trust:.2f} (data_factor={data_factor:.2f}, n={n}, "
        f"consensus={consensus_score:.2f}); raw_dev={raw_dev:+.3f} -> {shrunk:+.3f}"
        + (" [CAPPED]" if capped else "")
    )
    logger.info(
        f"Calibration: my_prob={my_prob:.3f} mkt={market_price:.3f} "
        f"-> calibrated={calibrated:.3f} | {reason}"
    )
    return {"calibrated_prob": round(calibrated, 4), "raw_prob": my_prob,
            "factor": round(trust, 3), "capped": capped, "reason": reason}
