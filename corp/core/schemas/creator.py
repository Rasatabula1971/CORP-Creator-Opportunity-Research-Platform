from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.creator import CreatorStatus


class CreatorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    niche: str | None = None
    discovery_source: str | None = None
    notes: str | None = None


class PlatformAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    handle: str
    external_id: str | None = None
    subscriber_count: int | None = None


class CreatorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    niche: str | None
    discovery_source: str | None
    status: CreatorStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


class PlatformAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    creator_id: str
    platform: str
    handle: str
    external_id: str | None
    subscriber_count: int | None
    verified: bool


class CreatorDetailResponse(CreatorResponse):
    platform_accounts: list[PlatformAccountResponse] = []
