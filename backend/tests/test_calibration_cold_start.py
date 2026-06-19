"""
Cold-start calibration safeguard.

Below CALIBRATION_MIN_SAMPLES opinionated outcomes, overconfidence_factor can't
be measured and defaults to 1.0 (no shrink) — so a raw LLM edge would otherwise
flow into Kelly capped only at the loose MAX_PROB_DEVIATION (0.15). The cold-start
rule instead clamps the claimed edge to COLD_START_MAX_DEVIATION (0.05) until the
model has earned trust.
"""
import pytest

from config import (
    CALIBRATION_MIN_SAMPLES, MAX_PROB_DEVIATION, COLD_START_MAX_DEVIATION,
)
from risk.calibration import calibrate_probability


def _samples(n, my_prob=0.7, win=1):
    """n opinionated samples (predicted away from 0.5) with a given outcome."""
    return [{"my_prob": my_prob, "win": win} for _ in range(n)]


# ── Cold start (too few samples) ──────────────────────────────────────────────

def test_cold_start_clamps_positive_edge_to_005():
    # Huge claimed edge, no history: clamp to market + 0.05.
    r = calibrate_probability(0.90, 0.50, samples=[], consensus_score=0.0)
    assert r["cold_start"] is True
    assert r["capped"] is True
    assert r["calibrated_prob"] == pytest.approx(0.55)


def test_cold_start_clamps_negative_edge_to_005():
    r = calibrate_probability(0.10, 0.50, samples=[], consensus_score=0.0)
    assert r["cold_start"] is True
    assert r["calibrated_prob"] == pytest.approx(0.45)


def test_cold_start_small_edge_passes_through_uncapped():
    # An edge already within the cold cap is untouched (trust=1.0 with no data).
    r = calibrate_probability(0.53, 0.50, samples=[], consensus_score=0.0)
    assert r["cold_start"] is True
    assert r["capped"] is False
    assert r["calibrated_prob"] == pytest.approx(0.53)


def test_just_below_threshold_is_cold(monkeypatch):
    samples = _samples(CALIBRATION_MIN_SAMPLES - 1)
    r = calibrate_probability(0.90, 0.50, samples=samples, consensus_score=0.0)
    assert r["cold_start"] is True
    # Clamped at the tight cap, not 0.15.
    assert abs(r["calibrated_prob"] - 0.50) == pytest.approx(COLD_START_MAX_DEVIATION)


# ── Warm (enough samples) ─────────────────────────────────────────────────────

def test_at_threshold_is_not_cold():
    # Exactly CALIBRATION_MIN_SAMPLES opinionated, well-calibrated (factor ~1.0):
    # the loose 0.15 cap applies, so a 0.40 edge clamps to 0.15, not 0.05.
    samples = _samples(CALIBRATION_MIN_SAMPLES, my_prob=0.7, win=1)
    r = calibrate_probability(0.90, 0.50, samples=samples, consensus_score=0.0)
    assert r["cold_start"] is False
    assert r["calibrated_prob"] == pytest.approx(0.50 + MAX_PROB_DEVIATION)  # 0.65


def test_warm_allows_larger_edge_than_cold():
    # Same inputs, only sample count differs => warm bets a bigger edge than cold.
    cold = calibrate_probability(0.90, 0.50, samples=[], consensus_score=0.0)
    warm = calibrate_probability(
        0.90, 0.50, samples=_samples(CALIBRATION_MIN_SAMPLES, win=1), consensus_score=0.0
    )
    assert warm["calibrated_prob"] > cold["calibrated_prob"]


# ── Disabled short-circuit still reports the new key ──────────────────────────

def test_disabled_calibration_reports_cold_start_false(monkeypatch):
    import risk.calibration as cal
    monkeypatch.setattr(cal, "CALIBRATION_ENABLED", False)
    r = cal.calibrate_probability(0.90, 0.50, samples=[], consensus_score=0.0)
    assert r["calibrated_prob"] == 0.90  # untouched
    assert r["cold_start"] is False
