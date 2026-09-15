from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.campaign_niche import CampaignNicheStatus
from corp.core.schemas.niche import NicheResponse


class CampaignNicheCreate(BaseModel):
    campaign_id: str
    niche_id: str
    discovery_rank: int | None = None
    target_band_creator_count: int | None = None


class CampaignNicheResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    campaign_id: str
    niche_id: str
    discovery_rank: int | None
    qualification_score: float | None
    confidence: float | None
    research_completeness: float | None
    creator_count_observed: int
    target_band_creator_count: int | None
    status: CampaignNicheStatus
    selected: bool
    rationale: str | None
    created_at: datetime
    updated_at: datetime


class CampaignNicheDetailResponse(CampaignNicheResponse):
    niche: NicheResponse
