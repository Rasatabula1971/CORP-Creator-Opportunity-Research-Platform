from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.workflow import DecisionType, Gate


class DecisionCreate(BaseModel):
    opportunity_score_id: str | None = None
    decision: DecisionType
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


class PipelineStepResponse(BaseModel):
    name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    detail: dict | None = None


class ResearchRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    campaign_id: str | None = None
    niche_id: str | None = None
    creator_id: str | None
    run_type: str = "creator_research"
    scope: str = "creator"
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    config_snapshot: dict | None
    prompt_versions: dict | None
    model_versions: dict | None
    stats: dict | None = None
    error_message: str | None
    steps: list[PipelineStepResponse] | None = None
    created_at: datetime
