"""DB-backed tests for the human-gate headroom that limits a research batch."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.niche import Niche, NicheLifecycleStatus
from corp.workers.campaign_config import (
    CampaignNotFoundError,
    batch_config,
    human_gate_occupancy,
    load_campaign,
)

pytestmark = pytest.mark.asyncio


async def _niche(
    session: AsyncSession, campaign: Campaign, name: str,
    *, status: CampaignNicheStatus = CampaignNicheStatus.SELECTED,
) -> Niche:
    niche = Niche(
        canonical_name=name,
        lifecycle_status=NicheLifecycleStatus.ACTIVE,
        last_researched_at=datetime.now(UTC),
    )
    session.add(niche)
    await session.flush()
    session.add(CampaignNiche(campaign_id=campaign.id, niche_id=niche.id, status=status))
    await session.flush()
    return niche


async def _creator(
    session: AsyncSession, niche: Niche, name: str, status: CreatorStatus,
) -> Creator:
    creator = Creator(name=name, status=status, discovery_source="test")
    session.add(creator)
    await session.flush()
    session.add(CreatorNiche(creator_id=creator.id, niche_id=niche.id))
    await session.flush()
    return creator


async def test_batch_limit_is_capacity_minus_creators_waiting_at_the_gate(
    clean_db: AsyncSession,
):
    session = clean_db
    campaign = Campaign(name="Gate", human_gate_capacity=5)
    session.add(campaign)
    await session.flush()
    niche = await _niche(session, campaign, "Selected niche")

    for i in range(3):
        await _creator(session, niche, f"Waiting {i}", CreatorStatus.HUMAN_REVIEW)
    # Not at the gate: still to be researched, or already decided.
    await _creator(session, niche, "Fresh", CreatorStatus.DISCOVERED)
    await _creator(session, niche, "Approved", CreatorStatus.APPROVED)

    assert await human_gate_occupancy(session, campaign.id) == 3
    assert (await batch_config(session, campaign)).limit == 2


async def test_full_gate_leaves_zero_headroom_not_negative(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Full gate", human_gate_capacity=2)
    session.add(campaign)
    await session.flush()
    niche = await _niche(session, campaign, "Selected niche")
    for i in range(4):
        await _creator(session, niche, f"Waiting {i}", CreatorStatus.HUMAN_REVIEW)

    assert (await batch_config(session, campaign)).limit == 0


async def test_gate_occupancy_counts_only_this_campaigns_selected_niches(
    clean_db: AsyncSession,
):
    session = clean_db
    campaign = Campaign(name="Mine", human_gate_capacity=10)
    other = Campaign(name="Theirs", human_gate_capacity=10)
    session.add_all([campaign, other])
    await session.flush()

    selected = await _niche(session, campaign, "Selected")
    rejected = await _niche(
        session, campaign, "Rejected", status=CampaignNicheStatus.REJECTED,
    )
    theirs = await _niche(session, other, "Other campaign")

    # A creator under two of this campaign's SELECTED niches counts once.
    shared = await _creator(session, selected, "Shared", CreatorStatus.HUMAN_REVIEW)
    second = await _niche(session, campaign, "Second selected")
    session.add(CreatorNiche(creator_id=shared.id, niche_id=second.id))
    await _creator(session, rejected, "Under rejected niche", CreatorStatus.HUMAN_REVIEW)
    await _creator(session, theirs, "Other campaign's", CreatorStatus.HUMAN_REVIEW)
    await session.flush()

    assert await human_gate_occupancy(session, campaign.id) == 1
    assert (await batch_config(session, campaign)).limit == 9


async def test_load_campaign_rejects_an_unknown_id(clean_db: AsyncSession):
    with pytest.raises(CampaignNotFoundError):
        await load_campaign(clean_db, "00000000-0000-0000-0000-000000000000")
