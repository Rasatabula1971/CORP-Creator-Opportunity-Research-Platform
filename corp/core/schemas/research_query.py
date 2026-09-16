from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.research_query import ResearchQueryStatus


class ResearchQueryCreate(BaseModel):
    research_run_id: str
    source: str
    query: str
    results_seen: int = 0
    new_results: int = 0
    duplicate_results: int = 0
    archive_reference: str | None = None
    status: ResearchQueryStatus = ResearchQueryStatus.SUCCEEDED
    error: str | None = None


class ResearchQueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    research_run_id: str
    source: str
    query: str
    executed_at: datetime
    results_seen: int
    new_results: int
    duplicate_results: int
    archive_reference: str | None
    status: ResearchQueryStatus
    error: str | None
    created_at: datetime
