from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.scoring import ConfidenceBand


class ScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    creator_id: str
    component_scores: dict
    aggregate_score: float
    computed_hash: str
    confidence_band: ConfidenceBand
    rule_version: str
    model_version: str
    created_at: datetime


class OpportunityScoreResponse(ScoreResponse):
    problem_cluster_id: str
