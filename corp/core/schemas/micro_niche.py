from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from corp.core.models.micro_niche import MicroNicheStatus


class MicroNicheResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    status: MicroNicheStatus
    problem_cluster_id: str | None
    creator_id: str | None
    creator_niche: str | None
    follower_count: int | None
    total_frequency: int
    source_creator_count: int
    sources: list[dict[str, Any]]
    decided_at: datetime | None
    decided_by: str | None
    decision_note: str | None
    approved_topic: str | None
    discovery_job_id: str | None
    created_at: datetime
    updated_at: datetime
