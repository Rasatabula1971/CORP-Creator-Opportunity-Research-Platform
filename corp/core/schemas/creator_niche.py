from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CreatorNicheCreate(BaseModel):
    creator_id: str
    niche_id: str
    discovery_run_id: str | None = None
    confidence: float | None = None


class CreatorNicheResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    creator_id: str
    niche_id: str
    discovery_run_id: str | None
    confidence: float | None
    first_observed_at: datetime
    last_observed_at: datetime
