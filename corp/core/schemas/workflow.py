from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from corp.core.models.workflow import DecisionType, Gate


class DecisionCreate(BaseModel):
    """Gate A (creator-level) decision. research_more belongs to the dossier
    gate (POST /dossiers/{id}/decision), so it is rejected here at
    validation time rather than by the gate logic (R10, after R9)."""

    model_config = ConfigDict(extra="forbid")

    opportunity_score_id: str | None = None
    decision: Literal[DecisionType.APPROVE, DecisionType.REJECT, DecisionType.WATCH]
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
    detail: dict[str, Any] | None = None


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
    config_snapshot: dict[str, Any] | None
    prompt_versions: dict[str, Any] | None
    model_versions: dict[str, Any] | None
    stats: dict[str, Any] | None = None
    error_message: str | None
    steps: list[PipelineStepResponse] | None = None
    created_at: datetime
