from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.campaign import CampaignStatus


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    research_profile_version: str | None = None
    target_niche_count: int = 10
    initial_creators_per_niche: int = 10
    creator_min_followers: int = 10_000
    creator_max_followers: int = 200_000
    human_gate_capacity: int = 50


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: CampaignStatus
    research_profile_version: str | None
    target_niche_count: int
    initial_creators_per_niche: int
    creator_min_followers: int
    creator_max_followers: int
    human_gate_capacity: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
