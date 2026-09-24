"""Integration tests for NicheSelector against real Postgres."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.niche import Niche, NicheLifecycleStatus
from corp.workers.intelligence.niche_selection import NicheSelector, SelectionConfig


async def _make_niche(
    session: AsyncSession,
    campaign: Campaign,
    name: str,
    *,
    score: float | None,
    confidence: float | None = 0.8,
    status: CampaignNicheStatus = CampaignNicheStatus.VERIFIED,
) -> CampaignNiche:
    niche = Niche(
        canonical_name=name,
        lifecycle_status=NicheLifecycleStatus.ACTIVE,
        last_researched_at=datetime.now(UTC),
    )
    session.add(niche)
    await session.flush()

    cn = CampaignNiche(
        campaign_id=campaign.id,
        niche_id=niche.id,
        status=status,
        qualification_score=score,
        confidence=confidence,
    )
    session.add(cn)
    await session.flush()
    return cn


@pytest.mark.asyncio
async def test_selects_top_n_by_score(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    cn_a = await _make_niche(session, campaign, "Niche A", score=0.9)
    cn_b = await _make_niche(session, campaign, "Niche B", score=0.7)
    cn_c = await _make_niche(session, campaign, "Niche C", score=0.5)

    selector = NicheSelector(session, SelectionConfig(top_n=2))
    run = await selector.select(campaign.id)

    assert run.status == "completed"
    extra = run.stats["extra"]
    assert extra["niches_ranked"] == 3
    assert extra["selected"] == 2
    assert extra["rejected"] == 1

    await session.refresh(cn_a)
    await session.refresh(cn_b)
    await session.refresh(cn_c)
    assert cn_a.status == CampaignNicheStatus.SELECTED
    assert cn_b.status == CampaignNicheStatus.SELECTED
    assert cn_c.status == CampaignNicheStatus.REJECTED
    assert cn_a.selected is True
    assert cn_c.selected is False


@pytest.mark.asyncio
async def test_rejects_below_min_score(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    cn_high = await _make_niche(session, campaign, "High", score=0.8)
    cn_low = await _make_niche(session, campaign, "Low", score=0.2)

    selector = NicheSelector(session, SelectionConfig(top_n=5, min_score=0.5))
    await selector.select(campaign.id)

    await session.refresh(cn_high)
    await session.refresh(cn_low)
    assert cn_high.status == CampaignNicheStatus.SELECTED
    assert cn_low.status == CampaignNicheStatus.REJECTED
    assert "below minimum" in cn_low.rationale


@pytest.mark.asyncio
async def test_rejects_below_min_confidence(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    cn_confident = await _make_niche(
        session, campaign, "Confident", score=0.8, confidence=0.9,
    )
    cn_unsure = await _make_niche(
        session, campaign, "Unsure", score=0.8, confidence=0.1,
    )

    selector = NicheSelector(session, SelectionConfig(top_n=5, min_confidence=0.5))
    await selector.select(campaign.id)

    await session.refresh(cn_confident)
    await session.refresh(cn_unsure)
    assert cn_confident.status == CampaignNicheStatus.SELECTED
    assert cn_unsure.status == CampaignNicheStatus.REJECTED
    assert "confidence" in cn_unsure.rationale


@pytest.mark.asyncio
async def test_already_decided_niches_skipped(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    cn_selected = await _make_niche(
        session, campaign, "Already Selected", score=0.9,
        status=CampaignNicheStatus.SELECTED,
    )
    cn_selected.rationale = "prior rationale"
    await session.flush()

    selector = NicheSelector(session, SelectionConfig(top_n=5))
    run = await selector.select(campaign.id)

    assert run.stats["extra"]["niches_ranked"] == 0
    await session.refresh(cn_selected)
    assert cn_selected.rationale == "prior rationale"


@pytest.mark.asyncio
async def test_skips_unqualified_niches(clean_db: AsyncSession):
    """VERIFIED niches without a qualification_score are not touched."""
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    cn_unscored = await _make_niche(session, campaign, "Unscored", score=None)

    selector = NicheSelector(session, SelectionConfig(top_n=5))
    run = await selector.select(campaign.id)

    assert run.stats["extra"]["niches_ranked"] == 0
    await session.refresh(cn_unscored)
    assert cn_unscored.status == CampaignNicheStatus.VERIFIED


@pytest.mark.asyncio
async def test_empty_campaign(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Empty")
    session.add(campaign)
    await session.flush()

    selector = NicheSelector(session, SelectionConfig())
    run = await selector.select(campaign.id)

    assert run.status == "completed"
    assert run.stats["extra"]["niches_ranked"] == 0


@pytest.mark.asyncio
async def test_ties_broken_by_name(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    cn_b = await _make_niche(session, campaign, "Beta", score=0.5)
    cn_a = await _make_niche(session, campaign, "Alpha", score=0.5)

    selector = NicheSelector(session, SelectionConfig(top_n=1))
    run = await selector.select(campaign.id)

    results = run.stats["extra"]["results"]
    assert results[0]["niche"] == "Alpha"
    assert results[1]["niche"] == "Beta"

    await session.refresh(cn_a)
    await session.refresh(cn_b)
    assert cn_a.status == CampaignNicheStatus.SELECTED
    assert cn_b.status == CampaignNicheStatus.REJECTED


@pytest.mark.asyncio
async def test_all_niches_fit_within_top_n(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    cn_a = await _make_niche(session, campaign, "A", score=0.9)
    cn_b = await _make_niche(session, campaign, "B", score=0.8)

    selector = NicheSelector(session, SelectionConfig(top_n=5))
    run = await selector.select(campaign.id)

    assert run.stats["extra"]["selected"] == 2
    assert run.stats["extra"]["rejected"] == 0
    await session.refresh(cn_a)
    await session.refresh(cn_b)
    assert cn_a.status == CampaignNicheStatus.SELECTED
    assert cn_b.status == CampaignNicheStatus.SELECTED


@pytest.mark.asyncio
async def test_cap_is_cumulative_across_passes(clean_db: AsyncSession):
    """Audit fix: top_n bounds the campaign's SELECTED total, not each
    invocation. The standing autonomous campaign runs select() on every
    pass over a list that already holds earlier winners; counting from
    zero each time grew it 5 -> 10 -> 15, each tier automatically
    onboarded and researched. Five already selected plus three newly
    verified must leave exactly five."""
    session = clean_db
    campaign = Campaign(name="Cumulative")
    session.add(campaign)
    await session.flush()

    prior = [
        await _make_niche(
            session, campaign, f"Prior {i}", score=0.9,
            status=CampaignNicheStatus.SELECTED,
        )
        for i in range(5)
    ]
    fresh = [
        await _make_niche(session, campaign, f"Fresh {i}", score=0.95) for i in range(3)
    ]

    run = await NicheSelector(session, SelectionConfig(top_n=5)).select(campaign.id)

    extra = run.stats["extra"]
    assert extra["already_selected"] == 5
    assert extra["selected"] == 0
    assert extra["rejected"] == 3
    assert extra["total_selected"] == 5
    for cn in fresh:
        await session.refresh(cn)
        assert cn.status == CampaignNicheStatus.REJECTED
        assert "5 already selected" in cn.rationale
    for cn in prior:
        await session.refresh(cn)
        assert cn.status == CampaignNicheStatus.SELECTED, "earlier winners keep their place"


@pytest.mark.asyncio
async def test_new_candidates_fill_only_the_remaining_headroom(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Headroom")
    session.add(campaign)
    await session.flush()

    for i in range(3):
        await _make_niche(
            session, campaign, f"Prior {i}", score=0.9,
            status=CampaignNicheStatus.SELECTED,
        )
    best = await _make_niche(session, campaign, "Best", score=0.99)
    mid = await _make_niche(session, campaign, "Mid", score=0.80)
    worst = await _make_niche(session, campaign, "Worst", score=0.60)

    run = await NicheSelector(session, SelectionConfig(top_n=5)).select(campaign.id)

    assert run.stats["extra"]["selected"] == 2
    assert run.stats["extra"]["total_selected"] == 5
    await session.refresh(best)
    await session.refresh(mid)
    await session.refresh(worst)
    assert best.status == CampaignNicheStatus.SELECTED
    assert mid.status == CampaignNicheStatus.SELECTED
    assert worst.status == CampaignNicheStatus.REJECTED


@pytest.mark.asyncio
async def test_rejected_niches_marked_terminal(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    for i in range(4):
        await _make_niche(session, campaign, f"Niche {i}", score=0.9 - i * 0.1)

    selector = NicheSelector(session, SelectionConfig(top_n=2))
    run = await selector.select(campaign.id)

    assert run.stats["extra"]["selected"] == 2
    assert run.stats["extra"]["rejected"] == 2
