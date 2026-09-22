"""Unit tests for scoring_v2 components and the lexical helpers — pure functions."""

import pytest

from corp.core.scoring.engine import (
    compute_score,
    growth_ratio,
    load_scoring_rules,
    score_competition_saturation,
    score_creator_content_alignment,
    score_cross_platform_consistency,
    score_engagement_velocity,
    weighted_evidence_count,
)
from corp.core.scoring.text import containment, jaccard, tokens


def test_rules_v2_weights_sum_to_one_and_cover_ten_components():
    rules = load_scoring_rules("rules/scoring.yaml")
    weights = rules["weights"]
    assert rules["version"] == "2.3.0"
    assert len(weights) == 14
    assert sum(weights.values()) == pytest.approx(1.0)
    v2_new = {"engagement_velocity", "creator_content_alignment", "cross_platform_consistency"}
    assert v2_new <= set(weights)
    # Both saturation signals ship side by side after the integration merge.
    assert {"competition_saturation", "competitor_saturation"} <= set(weights)
    # T7/T21 evidence-type components.
    t7_new = {
        "external_demand_strength",
        "solution_saturation",
        "purchase_intent",
        "audience_dissatisfaction",
    }
    assert t7_new <= set(weights)


def test_weighted_evidence_count_discounts_scraped_rows():
    assert weighted_evidence_count({"official": 10}) == 10.0
    assert weighted_evidence_count({"open": 10}) == 8.0
    assert weighted_evidence_count({"vendor_scrape": 10}) == 5.0
    assert weighted_evidence_count({"official": 4, "vendor_scrape": 2, "unknown": 2}) == 6.0
    assert weighted_evidence_count({}) == 0.0


@pytest.mark.parametrize(
    "earliest, latest, expected",
    [(100, 150, 0.5), (100, 50, -0.5), (None, 10, None), (0, 10, None), (10, None, None)],
)
def test_growth_ratio(earliest, latest, expected):
    assert growth_ratio(earliest, latest) == expected


def test_engagement_velocity_neutral_when_unknown_and_monotone():
    assert score_engagement_velocity(None) == 0.5
    assert score_engagement_velocity(0.0) == 0.5
    assert score_engagement_velocity(1.0) > score_engagement_velocity(0.2) > 0.5
    assert score_engagement_velocity(-0.5) < 0.5
    assert 0.0 <= score_engagement_velocity(-100) <= score_engagement_velocity(100) <= 1.0


def test_competition_saturation():
    assert score_competition_saturation() == 0.5  # no creator-web evidence
    assert score_competition_saturation(None, 5) == 0.5
    assert score_competition_saturation(0.0, 0) == 1.0  # web evidence, nothing overlapping
    assert score_competition_saturation(1.0, 0) == pytest.approx(0.3)
    assert score_competition_saturation(0.5, 4) == pytest.approx(0.52, abs=0.01)
    assert score_competition_saturation(1.0, 20) == pytest.approx(0.054, abs=0.01)
    assert score_competition_saturation(0.0, 4) < score_competition_saturation(0.0, 0)


def test_creator_content_alignment():
    assert score_creator_content_alignment(0) == 0.0
    assert score_creator_content_alignment(1) == pytest.approx(1 / 3)
    assert score_creator_content_alignment(3) == 1.0
    assert score_creator_content_alignment(9) == 1.0


def test_cross_platform_consistency():
    assert score_cross_platform_consistency(1, 1) == 0.5  # nothing to compare against
    assert score_cross_platform_consistency(0, 0) == 0.5
    assert score_cross_platform_consistency(1, 2) == 0.5
    assert score_cross_platform_consistency(2, 2) == 1.0
    assert score_cross_platform_consistency(0, 3) == 0.0


def test_v2_aggregate_uses_all_weights():
    rules = load_scoring_rules("rules/scoring.yaml")
    ones = {k: 1.0 for k in rules["weights"]}
    assert compute_score(ones, rules["weights"]) == pytest.approx(1.0)
    half = dict(ones, commercial_intent_strength=0.0)
    expected = 1.0 - rules["weights"]["commercial_intent_strength"]
    assert compute_score(half, rules["weights"]) == pytest.approx(expected)


def test_tokens_strip_stopwords_and_lowercase():
    t = tokens("Where can I buy a Battery replacement for the camera?")
    assert "battery" in t and "replacement" in t and "camera" in t and "buy" in t
    assert "the" not in t and "i" not in t and "a" not in t
    assert tokens(None) == frozenset() and tokens("") == frozenset()


def test_jaccard_and_containment():
    a = tokens("battery drains fast on the phone")
    b = tokens("phone battery drain problems")
    assert 0.0 < jaccard(a, b) < 1.0
    assert jaccard(a, frozenset()) == 0.0
    page = tokens("Our shop sells battery packs, phone cases and camera mounts for creators")
    assert containment(tokens("battery packs"), page) == 1.0
    assert containment(tokens("tripod"), page) == 0.0
    assert containment(frozenset(), page) == 0.0
