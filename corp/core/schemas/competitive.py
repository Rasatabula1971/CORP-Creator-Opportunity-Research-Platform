from pydantic import BaseModel, ConfigDict

from corp.core.models.competitive import CompetitorStrength, CompetitorType


class CompetitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    problem_cluster_id: str
    name: str
    competitor_type: CompetitorType
    strength: CompetitorStrength
    url: str | None
    gap_notes: str | None
    evidence_id: str | None
