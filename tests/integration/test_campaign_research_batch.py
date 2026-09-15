"""Integration tests for CampaignResearchBatch against real Postgres.

Uses a FakeResearcher instead of the real ResearchOrchestrator so batch
selection/dedup/skip logic is verified without a live LLM provider or
yt-dlp collector.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.niche import Niche, NicheLifecycleStatus
from corp.workers.campaign_research import BatchConfig, CampaignResearchBatch


@dataclass
class _FakeReport:
    final_status: str = "human_review"


class FakeResearcher:
    def __init__(
        self,
        final_status: str = "human_review",
        raise_for: set[str] | None = None,
    ) -> None:
        self._final_status = final_status
        self._raise_for = raise_for or set()
        self.calls: list[tuple[str, bool]] = []

    async def run(self, creator_id: str, *, skip_collect: bool = False) -> _FakeReport:
        self.calls.append((creator_id, skip_collect))
        if creator_id in self._raise_for:
            raise RuntimeError(f"boom for {creator_id}")
        return _FakeReport(final_status=self._final_status)


# ── helpers ───────────────────────────────────────────────────────────


async def _make_campaign(session: AsyncSession) -> Campaign:
    campaign = Campaign(name="Test Campaign")
    session.add(campaign)
    await session.flush()
    return campaign


async def _selected_niche(session: AsyncSession, campaign: Campaign, name: str) -> Niche:
    niche = Niche(
        canonical_name=name,
        lifecycle_status=NicheLifecycleStatus.ACTIVE,
        last_researched_at=datetime.now(UTC),
    )
    session.add(niche)
    await session.flush()
    session.add(CampaignNiche(
        campaign_id=campaign.id, niche_id=niche.id, status=CampaignNicheStatus.SELECTED,
    ))
    await session.flush()
    return niche


async def _onboarded_creator(
    session: AsyncSession, niche: Niche, name: str,
    *, status: CreatorStatus = CreatorStatus.DISCOVERED,
) -> Creator:
    creator = Creator(name=name, status=status, discovery_source="test")
    session.add(creator)
    await session.flush()
    session.add(CreatorNiche(creator_id=creator.id, niche_id=niche.id))
    await session.flush()
    return creator


# ── tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_researches_eligible_creators(clean_db: AsyncSession):
    session = clean_db
    campaign = await _make_campaign(session)
    niche = await _selected_niche(session, campaign, "Home Espresso")
    await _onboarded_creator(session, niche, "Creator A")
    await _onboarded_creator(session, niche, "Creator B")

    researcher = FakeResearcher()
    batch = CampaignResearchBatch(researcher, session)
    run = await batch.run_campaign(campaign.id)

    assert run.status == "completed"
    extra = run.stats["extra"]
    assert extra["creators_total"] == 2
    assert extra["succeeded"] == 2
    assert len(researcher.calls) == 2


@pytest.mark.asyncio
async def test_skips_already_progressed_creators(clean_db: AsyncSession):
    session = clean_db
    campaign = await _make_campaign(session)
    niche = await _selected_niche(session, campaign, "Reef Aquarium")
    await _onboarded_creator(
        session, niche, "Already Approved", status=CreatorStatus.APPROVED,
    )

    researcher = FakeResearcher()
    batch = CampaignResearchBatch(researcher, session)
    run = await batch.run_campaign(campaign.id)

    assert run.stats["extra"]["skipped"] == 1
    assert len(researcher.calls) == 0


@pytest.mark.asyncio
async def test_force_reprocesses_already_progressed(clean_db: AsyncSession):
    session = clean_db
    campaign = await _make_campaign(session)
    niche = await _selected_niche(session, campaign, "Sim Racing")
    await _onboarded_creator(
        session, niche, "Already Approved", status=CreatorStatus.APPROVED,
    )

    researcher = FakeResearcher()
    batch = CampaignResearchBatch(researcher, session, BatchConfig(force=True))
    run = await batch.run_campaign(campaign.id)

    assert run.stats["extra"]["skipped"] == 0
    assert run.stats["extra"]["succeeded"] == 1
    assert len(researcher.calls) == 1


@pytest.mark.asyncio
async def test_only_selected_niches_creators_included(clean_db: AsyncSession):
    session = clean_db
    campaign = await _make_campaign(session)

    verified_niche = Niche(
        canonical_name="Not Yet Selected",
        lifecycle_status=NicheLifecycleStatus.ACTIVE,
        last_researched_at=datetime.now(UTC),
    )
    session.add(verified_niche)
    await session.flush()
    session.add(CampaignNiche(
        campaign_id=campaign.id, niche_id=verified_niche.id,
        status=CampaignNicheStatus.VERIFIED,
    ))
    await session.flush()
    await _onboarded_creator(session, verified_niche, "Excluded Creator")

    researcher = FakeResearcher()
    batch = CampaignResearchBatch(researcher, session)
    run = await batch.run_campaign(campaign.id)

    assert run.stats["extra"]["creators_total"] == 0
    assert len(researcher.calls) == 0


@pytest.mark.asyncio
async def test_dedupes_creator_in_multiple_selected_niches(clean_db: AsyncSession):
    session = clean_db
    campaign = await _make_campaign(session)
    niche_a = await _selected_niche(session, campaign, "Niche A")
    niche_b = await _selected_niche(session, campaign, "Niche B")

    creator = Creator(name="Multi Niche Creator", discovery_source="test")
    session.add(creator)
    await session.flush()
    session.add(CreatorNiche(creator_id=creator.id, niche_id=niche_a.id))
    session.add(CreatorNiche(creator_id=creator.id, niche_id=niche_b.id))
    await session.flush()

    researcher = FakeResearcher()
    batch = CampaignResearchBatch(researcher, session)
    run = await batch.run_campaign(campaign.id)

    assert run.stats["extra"]["creators_total"] == 1
    assert len(researcher.calls) == 1


@pytest.mark.asyncio
async def test_respects_limit(clean_db: AsyncSession):
    session = clean_db
    campaign = await _make_campaign(session)
    niche = await _selected_niche(session, campaign, "Big Niche")
    for i in range(3):
        await _onboarded_creator(session, niche, f"Creator {i}")

    researcher = FakeResearcher()
    batch = CampaignResearchBatch(researcher, session, BatchConfig(limit=2))
    run = await batch.run_campaign(campaign.id)

    assert run.stats["extra"]["creators_total"] == 2
    assert len(researcher.calls) == 2


@pytest.mark.asyncio
async def test_handles_researcher_exception_gracefully(clean_db: AsyncSession):
    session = clean_db
    campaign = await _make_campaign(session)
    niche = await _selected_niche(session, campaign, "Mixed Results")
    bad = await _onboarded_creator(session, niche, "Bad Creator")
    await _onboarded_creator(session, niche, "Good Creator")

    researcher = FakeResearcher(raise_for={bad.id})
    batch = CampaignResearchBatch(researcher, session)
    run = await batch.run_campaign(campaign.id)

    assert run.status in ("completed", "partial")
    extra = run.stats["extra"]
    assert extra["errored"] == 1
    assert extra["succeeded"] == 1
    assert len(researcher.calls) == 2


@pytest.mark.asyncio
async def test_empty_campaign(clean_db: AsyncSession):
    session = clean_db
    campaign = await _make_campaign(session)

    researcher = FakeResearcher()
    batch = CampaignResearchBatch(researcher, session)
    run = await batch.run_campaign(campaign.id)

    assert run.status == "completed"
    assert run.stats["extra"]["creators_total"] == 0


@pytest.mark.asyncio
async def test_incomplete_report_counted_separately(clean_db: AsyncSession):
    session = clean_db
    campaign = await _make_campaign(session)
    niche = await _selected_niche(session, campaign, "Stopped Midway")
    await _onboarded_creator(session, niche, "Stalled Creator")

    researcher = FakeResearcher(final_status="collecting")
    batch = CampaignResearchBatch(researcher, session)
    run = await batch.run_campaign(campaign.id)

    extra = run.stats["extra"]
    assert extra["succeeded"] == 0
    assert extra["incomplete"] == 1


@pytest.mark.asyncio
async def test_skip_collect_passed_through(clean_db: AsyncSession):
    session = clean_db
    campaign = await _make_campaign(session)
    niche = await _selected_niche(session, campaign, "Skip Collect Niche")
    await _onboarded_creator(session, niche, "Creator")

    researcher = FakeResearcher()
    batch = CampaignResearchBatch(researcher, session, BatchConfig(skip_collect=True))
    await batch.run_campaign(campaign.id)

    assert researcher.calls == [(researcher.calls[0][0], True)]
