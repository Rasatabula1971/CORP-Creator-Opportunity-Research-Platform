from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.evidence import AccessMethod, ComplianceStatus


class EvidenceCreate(BaseModel):
    source_type: str
    source_id: str
    source_platform: str
    raw_text: str
    author_handle: str | None = None
    source_url: str | None = None
    access_method: AccessMethod
    compliance_status: ComplianceStatus
    research_run_id: str | None = None


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    source_id: str
    source_platform: str
    raw_text: str
    author_handle: str | None
    source_url: str | None
    access_method: AccessMethod
    compliance_status: ComplianceStatus
    collected_at: datetime
    research_run_id: str | None
