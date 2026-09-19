"""Unit tests for scoring engine component calculators and helpers."""

import math

from corp.core.models.competitive import CompetitorStrength
from corp.core.models.intent import SignalLevel
from corp.core.scoring.engine import (
    compute_hash,
    compute_score,
    get_score_band,
    score_audience_dissatisfaction,
    score_audience_problem_frequency,
    score_commercial_intent,
    score_competitor_saturation,
    score_creator_reach,
    score_evidence_depth,
    score_external_demand_strength,
    score_purchase_intent,
    score_recency_trend,
    score_solution_saturation,
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
    assert abs(s - 0.125) < 1e-10


async def test_commercial_intent_validation():
    s = score_commercial_intent(SignalLevel.VALIDATION, 1.0)
    assert s == 1.0


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


# Post-merge: the Competitor-list signal is score_competitor_saturation;
# score_competition_saturation now reads commerce-overlap (a float), tested
# in tests/core/test_scoring_v2.py.
async def test_competitor_saturation_neutral():
    assert score_competitor_saturation() == 0.5


async def test_competitor_saturation_empty_list_neutral():
    assert score_competitor_saturation([]) == 0.5


async def test_competitor_saturation_one_weak():
    s = score_competitor_saturation([CompetitorStrength.WEAK])
    assert abs(s - 0.9167) < 1e-4


async def test_competitor_saturation_mixed():
    s = score_competitor_saturation([CompetitorStrength.STRONG, CompetitorStrength.MODERATE])
    assert abs(s - 0.4667) < 1e-4


async def test_competitor_saturation_fully_saturated():
    s = score_competitor_saturation(
        [CompetitorStrength.STRONG, CompetitorStrength.STRONG, CompetitorStrength.STRONG]
    )
    assert s == 0.0


async def test_competitor_saturation_above_cap_clamped():
    s = score_competitor_saturation([CompetitorStrength.STRONG] * 5)
    assert s == 0.0


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


async def test_score_band_skips_band_without_min():
    # A band missing its "min" must not swallow every score (previously it
    # defaulted to 0.0 and matched everything as the first band).
    rules = {"score_bands": {
        "exceptional": {"label": "Exceptional"},          # no min
        "strong": {"min": 0.70, "label": "Strong"},
        "weak": {"min": 0.0, "label": "Weak"},
    }}
    assert get_score_band(0.9, rules) == "Strong"          # not "Exceptional"
    assert get_score_band(0.2, rules) == "Weak"


async def test_score_band_empty_rules_falls_back():
    assert get_score_band(0.9, {}) == "Weak — insufficient signal"


# ── CORP1 Stage 5, T7: capability-type components ────────────────────


async def test_external_demand_zero_evidence():
    assert score_external_demand_strength(0, 0) == 0.0


async def test_external_demand_trend_only():
    s = score_external_demand_strength(10, 0)
    assert 0.0 < s < 1.0


async def test_external_demand_search_intent_only():
    s = score_external_demand_strength(0, 10)
    assert 0.0 < s < 1.0


async def test_external_demand_combines_both_sources():
    trend_only = score_external_demand_strength(10, 0)
    combined = score_external_demand_strength(10, 10)
    assert combined > trend_only


async def test_external_demand_at_cap():
    assert score_external_demand_strength(30, 0, cap=30) == 1.0


async def test_external_demand_negative_treated_as_zero():
    assert score_external_demand_strength(-5, -5) == 0.0


async def test_solution_saturation_no_evidence_is_neutral():
    # Matches score_competition_saturation / score_competitor_saturation's
    # convention: absence of research is not evidence of an open market.
    assert score_solution_saturation(0) == 0.5


async def test_solution_saturation_few_solutions_high_score():
    s = score_solution_saturation(1, cap=20)
    assert 0.9 < s < 1.0


async def test_solution_saturation_at_cap_fully_saturated():
    assert score_solution_saturation(20, cap=20) == 0.0


async def test_solution_saturation_beyond_cap_stays_zero():
    assert score_solution_saturation(100, cap=20) == 0.0


async def test_purchase_intent_zero_evidence():
    assert score_purchase_intent(0) == 0.0


async def test_purchase_intent_positive():
    s = score_purchase_intent(5)
    assert 0.0 < s < 1.0


async def test_purchase_intent_at_cap():
    assert score_purchase_intent(15, cap=15) == 1.0


async def test_purchase_intent_monotonic():
    # More transaction evidence never scores lower.
    assert score_purchase_intent(10) >= score_purchase_intent(3)


async def test_audience_dissatisfaction_zero_evidence():
    assert score_audience_dissatisfaction(0) == 0.0


async def test_audience_dissatisfaction_positive():
    s = score_audience_dissatisfaction(8)
    assert 0.0 < s < 1.0


async def test_audience_dissatisfaction_at_cap():
    assert score_audience_dissatisfaction(20, cap=20) == 1.0


async def test_audience_dissatisfaction_higher_is_stronger_signal():
    # Unlike the saturation components, higher dissatisfaction evidence
    # means a STRONGER opportunity signal, not more crowding.
    assert score_audience_dissatisfaction(15) > score_audience_dissatisfaction(2)


async def test_scoring_yaml_weights_sum_to_one():
    """The real rules file, not a fixture -- catches a future rebalancing
    mistake directly, not just the engine's own math."""
    from corp.core.scoring.engine import load_scoring_rules

    rules = load_scoring_rules("rules/scoring.yaml")
    weights = rules["weights"]
    assert len(weights) == 14
    assert abs(sum(weights.values()) - 1.0) < 1e-9


async def test_scoring_yaml_weights_exact_values():
    """The sum-to-one check alone would let a silent reweighting (still
    summing to 1.0) slip through -- assert each weight against its exact
    expected value so an accidental edit to rules/scoring.yaml is caught
    here, not just downstream in an aggregate-score assertion."""
    from corp.core.scoring.engine import load_scoring_rules

    rules = load_scoring_rules("rules/scoring.yaml")
    weights = rules["weights"]
    expected = {
        "audience_problem_frequency": 0.152,
        "recency_trend": 0.038,
        "engagement_velocity": 0.076,
        "commercial_intent_strength": 0.152,
        "evidence_depth": 0.076,
        "creator_reach": 0.076,
        "competition_saturation": 0.038,
        "competitor_saturation": 0.038,
        "creator_content_alignment": 0.076,
        "cross_platform_consistency": 0.038,
        "external_demand_strength": 0.060,
        "solution_saturation": 0.040,
        "purchase_intent": 0.080,
        "audience_dissatisfaction": 0.060,
    }
    assert weights.keys() == expected.keys()
    for key, value in expected.items():
        assert abs(weights[key] - value) < 1e-9, key


async def test_new_dimensions_compute_score_with_existing_components():
    """A component_scores dict using only the original ten dimensions
    (the live scoring pipeline's current behavior, unchanged by this
    task) still normalizes correctly against the real 14-key weights
    file -- compute_score divides by the weight actually present, not
    the full weights dict."""
    from corp.core.scoring.engine import load_scoring_rules

    rules = load_scoring_rules("rules/scoring.yaml")
    weights = rules["weights"]
    components = {
        "audience_problem_frequency": 0.8,
        "recency_trend": 0.5,
        "commercial_intent_strength": 0.9,
    }
    score = compute_score(components, weights)
    assert 0.0 <= score <= 1.0


async def test_new_dimensions_compute_score_with_all_fourteen():
    from corp.core.scoring.engine import load_scoring_rules

    rules = load_scoring_rules("rules/scoring.yaml")
    weights = rules["weights"]
    components = dict.fromkeys(weights, 0.7)
    score = compute_score(components, weights)
    assert abs(score - 0.7) < 1e-9  # uniform input -> output equals that value
