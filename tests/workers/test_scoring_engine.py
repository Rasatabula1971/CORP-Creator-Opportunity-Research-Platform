"""Unit tests for scoring engine component calculators and helpers."""

import math

from corp.core.models.intent import SignalLevel
from corp.core.scoring.engine import (
    compute_hash,
    compute_score,
    get_score_band,
    score_audience_problem_frequency,
    score_commercial_intent,
    score_competition_saturation,
    score_creator_reach,
    score_evidence_depth,
    score_recency_trend,
)


# ── Component score calculators ──────────────────────────────────────


async def test_frequency_zero():
    assert score_audience_problem_frequency(0) == 0.0


async def test_frequency_positive():
    s = score_audience_problem_frequency(10)
    assert 0.0 < s < 1.0


async def test_frequency_at_cap():
    assert score_audience_problem_frequency(100) == 1.0


async def test_frequency_above_cap():
    assert score_audience_problem_frequency(500) == 1.0


async def test_frequency_negative():
    assert score_audience_problem_frequency(-5) == 0.0


async def test_recency_passthrough():
    assert score_recency_trend(0.7) == 0.7


async def test_recency_clamp_low():
    assert score_recency_trend(-0.1) == 0.0


async def test_recency_clamp_high():
    assert score_recency_trend(1.5) == 1.0


async def test_commercial_intent_strong():
    s = score_commercial_intent(SignalLevel.STRONG, 1.0)
    assert s == 0.75


async def test_commercial_intent_weak_low_confidence():
    s = score_commercial_intent(SignalLevel.WEAK, 0.5)
    assert abs(s - 0.075) < 1e-10


async def test_commercial_intent_validation():
    s = score_commercial_intent(SignalLevel.VALIDATION, 1.0)
    assert s == 0.95


async def test_commercial_intent_confidence_clamped():
    s = score_commercial_intent(SignalLevel.STRONG, 2.0)
    assert s == 0.75  # clamped to 1.0


async def test_evidence_depth_zero():
    assert score_evidence_depth(0) == 0.0


async def test_evidence_depth_positive():
    s = score_evidence_depth(10)
    expected = math.log1p(10) / math.log1p(50)
    assert abs(s - expected) < 1e-10


async def test_evidence_depth_at_cap():
    assert score_evidence_depth(50) == 1.0


async def test_creator_reach_none():
    assert score_creator_reach(None) == 0.0


async def test_creator_reach_zero():
    assert score_creator_reach(0) == 0.0


async def test_creator_reach_million():
    s = score_creator_reach(1_000_000)
    expected = math.log10(1_000_000) / 7.0
    assert abs(s - expected) < 1e-10


async def test_creator_reach_ten_million():
    assert score_creator_reach(10_000_000) == 1.0


async def test_creator_reach_above_cap():
    assert score_creator_reach(100_000_000) == 1.0


async def test_competition_saturation_neutral():
    assert score_competition_saturation() == 0.5


# ── Aggregate score ──────────────────────────────────────────────────


async def test_aggregate_weighted():
    components = {"a": 0.8, "b": 0.4}
    weights = {"a": 0.6, "b": 0.4}
    expected = (0.8 * 0.6 + 0.4 * 0.4) / (0.6 + 0.4)
    assert abs(compute_score(components, weights) - expected) < 1e-10


async def test_aggregate_missing_weight_ignored():
    components = {"a": 0.8, "b": 0.4}
    weights = {"a": 0.6}
    expected = 0.8
    assert abs(compute_score(components, weights) - expected) < 1e-10


# ── Hash determinism ─────────────────────────────────────────────────


async def test_hash_deterministic_across_key_order():
    c1 = {"b": 0.5, "a": 0.3}
    c2 = {"a": 0.3, "b": 0.5}
    assert compute_hash(c1, "v1") == compute_hash(c2, "v1")


# ── Score bands ──────────────────────────────────────────────────────


async def test_score_band_exceptional():
    rules = {"score_bands": {
        "exceptional": {"min": 0.85, "label": "Exceptional"},
        "strong": {"min": 0.70, "label": "Strong"},
        "moderate": {"min": 0.50, "label": "Moderate"},
        "weak": {"min": 0.0, "label": "Weak"},
    }}
    assert get_score_band(0.9, rules) == "Exceptional"


async def test_score_band_weak():
    rules = {"score_bands": {
        "exceptional": {"min": 0.85, "label": "Exceptional"},
        "strong": {"min": 0.70, "label": "Strong"},
        "moderate": {"min": 0.50, "label": "Moderate"},
        "weak": {"min": 0.0, "label": "Weak"},
    }}
    assert get_score_band(0.2, rules) == "Weak"
