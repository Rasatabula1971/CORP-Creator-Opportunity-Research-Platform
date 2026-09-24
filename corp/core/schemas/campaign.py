from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from corp.core.models.campaign import CampaignStatus

# Upper bounds are sanity caps, not product limits: each of these numbers
# drives real work in the automated chain (niches selected, creators
# searched and researched per niche, dossiers allowed at the gate), so an
# absurd value is a runaway cost, not a preference.
MAX_TARGET_NICHE_COUNT = 100
MAX_CREATORS_PER_NICHE = 100
MAX_HUMAN_GATE_CAPACITY = 1_000


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    research_profile_version: str | None = Field(default=None, max_length=50)
    target_niche_count: int = Field(default=10, ge=1, le=MAX_TARGET_NICHE_COUNT)
    initial_creators_per_niche: int = Field(default=10, ge=1, le=MAX_CREATORS_PER_NICHE)
    creator_min_followers: int = Field(default=10_000, ge=0)
    creator_max_followers: int = Field(default=200_000, ge=1)
    human_gate_capacity: int = Field(default=50, ge=1, le=MAX_HUMAN_GATE_CAPACITY)

    @model_validator(mode="after")
    def _follower_band_is_ordered(self) -> "CampaignCreate":
        # An inverted band is not a strict-but-valid filter: onboarding and
        # the ecosystem estimate would reject every creator and the
        # campaign would silently never produce a dossier.
        if self.creator_min_followers > self.creator_max_followers:
            raise ValueError(
                "creator_min_followers must not exceed creator_max_followers "
                f"({self.creator_min_followers} > {self.creator_max_followers})"
            )
        return self


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
