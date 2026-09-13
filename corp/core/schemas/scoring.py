from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.scoring import ConfidenceBand


class ComponentScores(BaseModel):
    audience_problem_frequency: float = 0.0
    recency_trend: float = 0.0
    commercial_intent_strength: float = 0.0
    evidence_depth: float = 0.0
    creator_reach: float = 0.0
    competition_saturation: float = 0.0


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
    research_run_id: str | None = None
    created_at: datetime


class OpportunityScoreResponse(ScoreResponse):
    problem_cluster_id: str
