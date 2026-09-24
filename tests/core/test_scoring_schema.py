"""ComponentScores must fail loudly on drift, not silently drop fields.

Audit finding: the schema listed only 10 of the 14 live scoring_v2
components, and Pydantic ignores unknown dict keys by default, so the
missing four (24% of the aggregate weight) vanished from every typed API
response with no test failure anywhere.
"""

import pytest
from pydantic import ValidationError

from corp.core.schemas.scoring import ComponentScores
from corp.core.scoring.engine import load_scoring_rules


def test_schema_lists_every_weighted_component():
    weights = load_scoring_rules("rules/scoring.yaml")["weights"]
    assert set(ComponentScores.model_fields) == set(weights)


def test_unknown_component_is_rejected_not_silently_dropped():
    with pytest.raises(ValidationError):
        ComponentScores.model_validate({"audience_problem_frequency": 0.5, "made_up": 1.0})


def test_all_fourteen_components_round_trip():
    payload = {
        "audience_problem_frequency": 0.1,
        "recency_trend": 0.2,
        "commercial_intent_strength": 0.3,
        "evidence_depth": 0.4,
        "creator_reach": 0.5,
        "competition_saturation": 0.6,
        "competitor_saturation": 0.7,
        "engagement_velocity": 0.8,
        "creator_content_alignment": 0.9,
        "cross_platform_consistency": 0.15,
        "external_demand_strength": 0.25,
        "solution_saturation": 0.35,
        "purchase_intent": 0.45,
        "audience_dissatisfaction": 0.55,
    }
    scores = ComponentScores.model_validate(payload)
    assert scores.model_dump() == payload
