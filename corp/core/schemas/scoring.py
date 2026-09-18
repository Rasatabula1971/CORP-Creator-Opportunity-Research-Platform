from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from corp.core.models.scoring import ConfidenceBand


class ComponentScores(BaseModel):
    """Typed view of the score components engine.py produces.

    Both saturation signals ship as independent components. commerce-overlap
    saturation (this branch's default) checks the creator's own storefront
    pages against each problem cluster; competitor_saturation (from main's
    Competitor list) counts how many DIRECT/SUBSTITUTE competitors exist
    per cluster. They contribute to the aggregate side by side; either can
    be 0.0 if that signal wasn't gathered.
    """

    audience_problem_frequency: float = 0.0
    recency_trend: float = 0.0
    commercial_intent_strength: float = 0.0
    evidence_depth: float = 0.0
    creator_reach: float = 0.0
    # Commerce-overlap saturation from creator-web PAGE content (this branch's
    # scoring_v2). Higher = the creator already sells something addressing the
    # problem, so the opportunity is more saturated.
    competition_saturation: float = 0.0
    # Explicit-Competitor-list saturation from the Competitor table (main's tier 2).
    # Higher = more known DIRECT/SUBSTITUTE competitors exist.
    competitor_saturation: float = 0.0
    # Engagement/growth signals (this branch's scoring_v2).
    engagement_velocity: float = 0.0
    creator_content_alignment: float = 0.0
    cross_platform_consistency: float = 0.0


class ScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    creator_id: str
    component_scores: ComponentScores
    aggregate_score: float
    computed_hash: str
    confidence_band: ConfidenceBand
    rule_version: str
    model_version: str
    diagnostics: dict[str, Any] | None = None
    created_at: datetime


class OpportunityScoreResponse(ScoreResponse):
    problem_cluster_id: str
