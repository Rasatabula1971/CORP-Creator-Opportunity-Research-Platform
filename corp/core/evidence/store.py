from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.evidence import (
    AccessMethod,
    ComplianceStatus,
    Evidence,
    EvidenceOrigin,
    EvidenceType,
)


async def create_evidence(
    session: AsyncSession,
    *,
    source_type: str,
    source_id: str,
    source_platform: str,
    raw_text: str,
    access_method: AccessMethod,
    compliance_status: ComplianceStatus,
    author_handle: str | None = None,
    source_url: str | None = None,
    research_run_id: str | None = None,
    evidence_type: EvidenceType | None = None,
    origin: EvidenceOrigin | None = None,
) -> Evidence:
    evidence = Evidence(
        source_type=source_type,
        source_id=source_id,
        source_platform=source_platform,
        raw_text=raw_text,
        access_method=access_method,
        compliance_status=compliance_status,
        author_handle=author_handle,
        source_url=source_url,
        research_run_id=research_run_id,
        evidence_type=evidence_type,
        origin=origin,
    )
    session.add(evidence)
    await session.flush()
    return evidence
