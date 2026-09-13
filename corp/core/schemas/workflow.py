from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.workflow import DecisionType, Gate


class DecisionCreate(BaseModel):
    creator_id: str
    opportunity_score_id: str | None = None
    decision: DecisionType
    gate: Gate
    rationale: str | None = None
    decided_by: str | None = None


class DecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    creator_id: str
    opportunity_score_id: str | None
    decision: DecisionType
    gate: Gate
    rationale: str | None
    decided_at: datetime
    decided_by: str | None


class ResearchRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    creator_id: str | None
    scope: str = "creator"
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    config_snapshot: dict | None
    prompt_versions: dict | None
    model_versions: dict | None
    stats: dict | None = None
    error_message: str | None
    created_at: datetime
