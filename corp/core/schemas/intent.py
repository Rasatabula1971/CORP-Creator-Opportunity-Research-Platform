from pydantic import BaseModel, ConfigDict

from corp.core.models.intent import SignalLevel


class CommercialSignalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    problem_cluster_id: str
    signal_level: SignalLevel
    evidence_id: str
    rationale: str | None
    confidence: float | None
    classification_model: str
    prompt_version: str
