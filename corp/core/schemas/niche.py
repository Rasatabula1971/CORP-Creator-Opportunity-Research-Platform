from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.niche import NicheLifecycleStatus, NichePolicyClass


class NicheCreate(BaseModel):
    canonical_name: str
    description: str | None = None
    parent_domain: str | None = None
    policy_class: NichePolicyClass = NichePolicyClass.STANDARD


class NicheAliasCreate(BaseModel):
    alias: str


class NicheAliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    niche_id: str
    alias: str


class NicheResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    canonical_name: str
    description: str | None
    parent_domain: str | None
    policy_class: NichePolicyClass
    lifecycle_status: NicheLifecycleStatus
    first_discovered_at: datetime
    last_researched_at: datetime | None
    next_recheck_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NicheDetailResponse(NicheResponse):
    aliases: list[NicheAliasResponse] = []
