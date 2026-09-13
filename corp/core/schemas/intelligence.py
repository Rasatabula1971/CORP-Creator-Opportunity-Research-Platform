from pydantic import BaseModel, ConfigDict


class ProblemObservationCreate(BaseModel):
    evidence_id: str
    text: str
    category: str | None = None
    is_inferred: bool = False
    extraction_prompt_version: str
    model_version: str
    confidence: float | None = None


class ProblemObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evidence_id: str
    text: str
    category: str | None
    is_inferred: bool
    sentiment: str | None = None
    urgency: str | None = None
    extraction_prompt_version: str
    model_version: str
    confidence: float | None


class ProblemClusterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    description: str | None
    frequency: int
    recency_score: float
    evidence_strength: float
    creator_count: int
    model_version: str | None = None
