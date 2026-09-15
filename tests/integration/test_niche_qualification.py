"""Integration tests for NicheQualifier against real Postgres."""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.niche import Niche, NicheLifecycleStatus
from corp.core.models.niche_candidate import NicheCandidate, NicheCandidateStatus
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.niche_qualification import NicheQualifier

RULES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "rules", "niche_qualification.yaml",
)


async def _setup_verified_niche(
    session: AsyncSession,
    niche_name: str,
    *,
    campaign: Campaign | None = None,
    evidence_count: int = 10,
    author_count: int = 5,
    is_broad_domain: bool = False,
    creator_count_observed: int = 0,
    target_band_creator_count: int = 0,
) -> tuple[Campaign, Niche, CampaignNiche, NicheCandidate]:
    if campaign is None:
        campaign = Campaign(name="Test Campaign")
        session.add(campaign)
        await session.flush()

    niche = Niche(
        canonical_name=niche_name,
        lifecycle_status=NicheLifecycleStatus.ACTIVE,
        last_researched_at=datetime.now(UTC),
    )
    session.add(niche)
    await session.flush()

    cn = CampaignNiche(
        campaign_id=campaign.id,
        niche_id=niche.id,
        status=CampaignNicheStatus.VERIFIED,
        creator_count_observed=creator_count_observed,
        target_band_creator_count=target_band_creator_count,
    )
    session.add(cn)
    await session.flush()

    run = ResearchRun(
        campaign_id=campaign.id,
        status="completed",
        config_snapshot={"pipeline": "test"},
    )
    session.add(run)
    await session.flush()

    candidate = NicheCandidate(
        campaign_id=campaign.id,
        research_run_id=run.id,
        label=niche_name,
        naming_method="keywords",
        evidence_count=evidence_count,
        source_count=1,
        author_count=author_count,
        is_broad_domain=is_broad_domain,
        status=NicheCandidateStatus.PROMOTED,
        niche_id=niche.id,
    )
    session.add(candidate)
    await session.flush()

    return campaign, niche, cn, candidate


@pytest.mark.asyncio
async def test_scores_single_niche(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, cn, _ = await _setup_verified_niche(
        session, "Home Espresso",
        evidence_count=20, author_count=10,
        creator_count_observed=8, target_band_creator_count=3,
    )

    qualifier = NicheQualifier(session, RULES_PATH)
    run = await qualifier.qualify_campaign(campaign.id)

    assert run.status == "completed"
    extra = run.stats["extra"]
    assert extra["niches_scored"] == 1
    r = extra["results"][0]
    assert r["niche"] == "Home Espresso"
    assert 0 < r["qualification_score"] <= 1.0
    assert 0 < r["confidence"] <= 1.0
    assert 0 < r["research_completeness"] <= 1.0

    await session.refresh(cn)
    assert cn.qualification_score == r["qualification_score"]
    assert cn.confidence == r["confidence"]
    assert cn.research_completeness == r["research_completeness"]


@pytest.mark.asyncio
async def test_high_evidence_gets_high_confidence(clean_db: AsyncSession):
    session = clean_db
    campaign, _, cn, _ = await _setup_verified_niche(
        session, "Rich Evidence Niche",
        evidence_count=30, author_count=15,
        creator_count_observed=20, target_band_creator_count=8,
    )

    qualifier = NicheQualifier(session, RULES_PATH)
    await qualifier.qualify_campaign(campaign.id)

    await session.refresh(cn)
    assert cn.confidence == 1.0


@pytest.mark.asyncio
async def test_low_evidence_gets_low_confidence(clean_db: AsyncSession):
    session = clean_db
    campaign, _, cn, _ = await _setup_verified_niche(
        session, "Sparse Niche",
        evidence_count=2, author_count=1,
        creator_count_observed=0, target_band_creator_count=0,
    )

    qualifier = NicheQualifier(session, RULES_PATH)
    await qualifier.qualify_campaign(campaign.id)

    await session.refresh(cn)
    assert cn.confidence <= 0.3


@pytest.mark.asyncio
async def test_broad_domain_penalised(clean_db: AsyncSession):
    session = clean_db
    campaign, _, cn_specific, _ = await _setup_verified_niche(
        session, "Specific Niche",
        evidence_count=10, author_count=5,
        creator_count_observed=5, target_band_creator_count=2,
    )
    _, _, cn_broad, _ = await _setup_verified_niche(
        session, "Broad Niche",
        campaign=campaign,
        evidence_count=10, author_count=5,
        is_broad_domain=True,
        creator_count_observed=5, target_band_creator_count=2,
    )

    qualifier = NicheQualifier(session, RULES_PATH)
    await qualifier.qualify_campaign(campaign.id)

    await session.refresh(cn_specific)
    await session.refresh(cn_broad)
    assert cn_specific.qualification_score > cn_broad.qualification_score


@pytest.mark.asyncio
async def test_ecosystem_boosts_score(clean_db: AsyncSession):
    session = clean_db
    campaign, _, cn_with, _ = await _setup_verified_niche(
        session, "With Ecosystem",
        evidence_count=10, author_count=5,
        creator_count_observed=15, target_band_creator_count=5,
    )
    _, _, cn_without, _ = await _setup_verified_niche(
        session, "Without Ecosystem",
        campaign=campaign,
        evidence_count=10, author_count=5,
        creator_count_observed=0, target_band_creator_count=0,
    )

    qualifier = NicheQualifier(session, RULES_PATH)
    await qualifier.qualify_campaign(campaign.id)

    await session.refresh(cn_with)
    await session.refresh(cn_without)
    assert cn_with.qualification_score > cn_without.qualification_score


@pytest.mark.asyncio
async def test_research_completeness_stages(clean_db: AsyncSession):
    session = clean_db
    campaign, _, cn_full, _ = await _setup_verified_niche(
        session, "Complete Niche",
        evidence_count=10, author_count=5,
        creator_count_observed=10, target_band_creator_count=3,
    )
    _, _, cn_partial, _ = await _setup_verified_niche(
        session, "Partial Niche",
        campaign=campaign,
        evidence_count=10, author_count=5,
        creator_count_observed=0, target_band_creator_count=0,
    )

    qualifier = NicheQualifier(session, RULES_PATH)
    await qualifier.qualify_campaign(campaign.id)

    await session.refresh(cn_full)
    await session.refresh(cn_partial)
    assert cn_full.research_completeness == 1.0
    assert cn_partial.research_completeness == 0.5


@pytest.mark.asyncio
async def test_empty_campaign(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Empty")
    session.add(campaign)
    await session.flush()

    qualifier = NicheQualifier(session, RULES_PATH)
    run = await qualifier.qualify_campaign(campaign.id)

    assert run.status == "completed"
    assert run.stats["extra"]["niches_scored"] == 0


@pytest.mark.asyncio
async def test_skips_non_verified(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    niche = Niche(
        canonical_name="Unverified",
        lifecycle_status=NicheLifecycleStatus.CANDIDATE,
    )
    session.add(niche)
    await session.flush()
    session.add(CampaignNiche(
        campaign_id=campaign.id,
        niche_id=niche.id,
        status=CampaignNicheStatus.DISCOVERED,
    ))
    await session.flush()

    qualifier = NicheQualifier(session, RULES_PATH)
    run = await qualifier.qualify_campaign(campaign.id)

    assert run.stats["extra"]["niches_scored"] == 0


@pytest.mark.asyncio
async def test_no_candidate_still_scores(clean_db: AsyncSession):
    """A verified niche without a promoted candidate still gets scored with zero evidence."""
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    niche = Niche(
        canonical_name="Orphan Niche",
        lifecycle_status=NicheLifecycleStatus.ACTIVE,
        last_researched_at=datetime.now(UTC),
    )
    session.add(niche)
    await session.flush()

    cn = CampaignNiche(
        campaign_id=campaign.id,
        niche_id=niche.id,
        status=CampaignNicheStatus.VERIFIED,
        creator_count_observed=5,
    )
    session.add(cn)
    await session.flush()

    qualifier = NicheQualifier(session, RULES_PATH)
    run = await qualifier.qualify_campaign(campaign.id)

    assert run.status == "completed"
    await session.refresh(cn)
    assert cn.qualification_score is not None
    assert cn.qualification_score >= 0


@pytest.mark.asyncio
async def test_deterministic_scoring(clean_db: AsyncSession):
    """Same inputs produce the same score on repeated runs."""
    session = clean_db
    campaign, _, cn, _ = await _setup_verified_niche(
        session, "Determinism Test",
        evidence_count=15, author_count=8,
        creator_count_observed=12, target_band_creator_count=4,
    )

    qualifier = NicheQualifier(session, RULES_PATH)

    await qualifier.qualify_campaign(campaign.id)
    await session.refresh(cn)
    score1 = cn.qualification_score

    await qualifier.qualify_campaign(campaign.id)
    await session.refresh(cn)
    score2 = cn.qualification_score

    assert score1 == score2
