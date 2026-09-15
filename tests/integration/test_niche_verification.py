"""Integration tests for NicheVerifier against real Postgres."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.niche import Niche, NicheLifecycleStatus
from corp.core.models.niche_candidate import (
    NicheCandidate,
    NicheCandidateEvidence,
    NicheCandidateStatus,
)
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.workers.intelligence.niche_verification import NicheVerifier, VerifyConfig

# ── helpers ───────────────────────────────────────────────────────────


async def _setup(
    session: AsyncSession,
    *,
    evidence_count: int = 10,
    author_count: int = 5,
    is_broad: bool = False,
    niche_name: str = "Home Espresso",
    campaign_name: str = "Test Campaign",
) -> tuple[Campaign, Niche, NicheCandidate]:
    campaign = Campaign(name=campaign_name)
    session.add(campaign)
    await session.flush()

    niche = Niche(
        canonical_name=niche_name,
        lifecycle_status=NicheLifecycleStatus.CANDIDATE,
    )
    session.add(niche)
    await session.flush()

    session.add(CampaignNiche(campaign_id=campaign.id, niche_id=niche.id))
    await session.flush()

    run = ResearchRun(
        creator_id=None,
        campaign_id=campaign.id,
        run_type=RunType.NICHE_DISCOVERY.value,
        scope=RunScope.NICHE.value,
        status="completed",
        config_snapshot={"pipeline": "niche_candidates"},
        prompt_versions={},
        model_versions={},
    )
    session.add(run)
    await session.flush()

    base = datetime(2026, 9, 1, tzinfo=UTC)
    cand = NicheCandidate(
        campaign_id=campaign.id,
        research_run_id=run.id,
        label=niche_name,
        naming_method="llm",
        evidence_count=evidence_count,
        source_count=1,
        author_count=author_count,
        is_broad_domain=is_broad,
        earliest_collected_at=base,
        latest_collected_at=base + timedelta(days=evidence_count),
        status=NicheCandidateStatus.PROMOTED,
        niche_id=niche.id,
        embedding_model="test",
    )
    session.add(cand)
    await session.flush()

    for i in range(evidence_count):
        ev = Evidence(
            source_type="video",
            source_id=f"vid-{i}",
            source_platform="youtube",
            raw_text=f"Evidence {i} about {niche_name}",
            author_handle=f"chan{i % author_count}",
            access_method=AccessMethod.VENDOR_SCRAPE,
            compliance_status=ComplianceStatus.VERIFY,
            research_run_id=run.id,
            collected_at=base + timedelta(days=i),
        )
        session.add(ev)
        await session.flush()
        session.add(NicheCandidateEvidence(
            candidate_id=cand.id, evidence_id=ev.id, similarity=0.9,
        ))
    await session.flush()

    return campaign, niche, cand


# ── tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_niche_passes_verification(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup(session, evidence_count=10, author_count=5)

    verifier = NicheVerifier(session, VerifyConfig(min_evidence=5, min_authors=3))
    run = await verifier.verify(campaign.id)

    assert run.status == "completed"
    extra = run.stats["extra"]
    assert extra["verified"] == 1
    assert extra["failed_verification"] == 0
    assert extra["results"][0]["passed"] is True

    await session.refresh(niche)
    assert niche.lifecycle_status == NicheLifecycleStatus.ACTIVE
    assert niche.last_researched_at is not None

    cn = (await session.execute(
        select(CampaignNiche).where(CampaignNiche.niche_id == niche.id)
    )).scalar_one()
    assert cn.status == CampaignNicheStatus.VERIFIED


@pytest.mark.asyncio
async def test_niche_fails_low_evidence(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup(session, evidence_count=2, author_count=5)

    verifier = NicheVerifier(session, VerifyConfig(min_evidence=5, min_authors=3))
    run = await verifier.verify(campaign.id)

    assert run.stats["extra"]["verified"] == 0
    assert run.stats["extra"]["failed_verification"] == 1
    assert "evidence_count=2 < 5" in run.stats["extra"]["results"][0]["reasons"][0]

    await session.refresh(niche)
    assert niche.lifecycle_status == NicheLifecycleStatus.CANDIDATE

    cn = (await session.execute(
        select(CampaignNiche).where(CampaignNiche.niche_id == niche.id)
    )).scalar_one()
    assert cn.status == CampaignNicheStatus.DISCOVERED
    assert "evidence_count" in cn.rationale


@pytest.mark.asyncio
async def test_niche_fails_low_authors(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup(session, evidence_count=10, author_count=1)

    verifier = NicheVerifier(session, VerifyConfig(min_evidence=5, min_authors=3))
    run = await verifier.verify(campaign.id)

    assert run.stats["extra"]["failed_verification"] == 1
    assert "author_count=1 < 3" in run.stats["extra"]["results"][0]["reasons"][0]

    await session.refresh(niche)
    assert niche.lifecycle_status == NicheLifecycleStatus.CANDIDATE


@pytest.mark.asyncio
async def test_broad_domain_rejected(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup(
        session, evidence_count=10, author_count=5, is_broad=True
    )

    verifier = NicheVerifier(session, VerifyConfig(reject_broad_domain=True))
    run = await verifier.verify(campaign.id)

    assert run.stats["extra"]["failed_verification"] == 1
    assert "is_broad_domain=True" in run.stats["extra"]["results"][0]["reasons"][0]


@pytest.mark.asyncio
async def test_broad_domain_allowed(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup(
        session, evidence_count=10, author_count=5, is_broad=True
    )

    verifier = NicheVerifier(session, VerifyConfig(reject_broad_domain=False))
    run = await verifier.verify(campaign.id)

    assert run.stats["extra"]["verified"] == 1
    await session.refresh(niche)
    assert niche.lifecycle_status == NicheLifecycleStatus.ACTIVE


@pytest.mark.asyncio
async def test_already_active_niche_is_skipped(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup(session)
    niche.lifecycle_status = NicheLifecycleStatus.ACTIVE
    await session.flush()

    verifier = NicheVerifier(session)
    run = await verifier.verify(campaign.id)

    assert run.stats["extra"]["candidates_checked"] == 1
    assert run.stats["extra"]["verified"] == 0
    assert run.stats["extra"]["failed_verification"] == 0


@pytest.mark.asyncio
async def test_empty_campaign_completes(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Empty")
    session.add(campaign)
    await session.flush()

    verifier = NicheVerifier(session)
    run = await verifier.verify(campaign.id)

    assert run.status == "completed"
    assert run.stats["extra"]["candidates_checked"] == 0
    assert run.stats["extra"]["verified"] == 0


@pytest.mark.asyncio
async def test_multiple_niches_mixed_results(clean_db: AsyncSession):
    session = clean_db
    campaign, niche1, _ = await _setup(
        session, evidence_count=10, author_count=5, niche_name="Good Niche"
    )
    # Add a second niche to the same campaign that will fail
    niche2 = Niche(
        canonical_name="Bad Niche",
        lifecycle_status=NicheLifecycleStatus.CANDIDATE,
    )
    session.add(niche2)
    await session.flush()
    session.add(CampaignNiche(campaign_id=campaign.id, niche_id=niche2.id))
    await session.flush()

    run_row = (await session.execute(
        select(ResearchRun).where(ResearchRun.campaign_id == campaign.id)
    )).scalar_one()

    cand2 = NicheCandidate(
        campaign_id=campaign.id,
        research_run_id=run_row.id,
        label="Bad Niche",
        naming_method="keywords",
        evidence_count=2,
        source_count=1,
        author_count=1,
        status=NicheCandidateStatus.PROMOTED,
        niche_id=niche2.id,
        embedding_model="test",
    )
    session.add(cand2)
    await session.flush()

    ev = Evidence(
        source_type="video",
        source_id="vid-bad-0",
        source_platform="youtube",
        raw_text="Bad niche evidence",
        author_handle="chan0",
        access_method=AccessMethod.VENDOR_SCRAPE,
        compliance_status=ComplianceStatus.VERIFY,
        research_run_id=run_row.id,
        collected_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    session.add(ev)
    await session.flush()
    session.add(NicheCandidateEvidence(
        candidate_id=cand2.id, evidence_id=ev.id, similarity=0.8,
    ))
    await session.flush()

    verifier = NicheVerifier(session, VerifyConfig(min_evidence=5, min_authors=3))
    run = await verifier.verify(campaign.id)

    assert run.stats["extra"]["verified"] == 1
    assert run.stats["extra"]["failed_verification"] == 1

    await session.refresh(niche1)
    await session.refresh(niche2)
    assert niche1.lifecycle_status == NicheLifecycleStatus.ACTIVE
    assert niche2.lifecycle_status == NicheLifecycleStatus.CANDIDATE
