"""Integration tests for EcosystemEstimator against real Postgres."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.niche import Niche, NicheLifecycleStatus
from corp.workers.intelligence.ecosystem_estimator import (
    EcoConfig,
    EcosystemEstimator,
)

# ── fake adapter ──────────────────────────────────────────────────────


class _FakeItem:
    def __init__(self, author: str, channel_id: str, follower_count: int | None):
        self.author = author
        self.metadata = {
            "channel_id": channel_id,
            "follower_count": follower_count,
        }


class FakeSearchAdapter:
    """Returns canned results keyed by niche name in the search query."""

    def __init__(self, results: dict[str, list[_FakeItem]]) -> None:
        self._results = results

    async def collect(self, identifier: str) -> list[_FakeItem]:
        for key, items in self._results.items():
            if key.lower() in identifier.lower():
                return items
        return []


# ── helpers ───────────────────────────────────────────────────────────


async def _setup_verified_niche(
    session: AsyncSession,
    niche_name: str,
    campaign: Campaign | None = None,
) -> tuple[Campaign, Niche, CampaignNiche]:
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
    )
    session.add(cn)
    await session.flush()

    return campaign, niche, cn


# ── tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_estimates_single_niche(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, cn = await _setup_verified_niche(session, "Home Espresso")

    adapter = FakeSearchAdapter({
        "Home Espresso": [
            _FakeItem("Chan A", "UCA", 50_000),
            _FakeItem("Chan B", "UCB", 150_000),
            _FakeItem("Chan C", "UCC", 5_000),
            _FakeItem("Chan D", "UCD", 500_000),
        ],
    })

    estimator = EcosystemEstimator(
        adapter, session, EcoConfig(min_followers=10_000, max_followers=200_000),
    )
    run = await estimator.estimate(campaign.id)

    assert run.status == "completed"
    extra = run.stats["extra"]
    assert extra["niches_checked"] == 1
    assert extra["results"][0]["total_creators"] == 4
    assert extra["results"][0]["target_band_creators"] == 2

    await session.refresh(cn)
    assert cn.creator_count_observed == 4
    assert cn.target_band_creator_count == 2


@pytest.mark.asyncio
async def test_deduplicates_channels(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, cn = await _setup_verified_niche(session, "Reef Aquarium")

    adapter = FakeSearchAdapter({
        "Reef Aquarium": [
            _FakeItem("Same Channel", "UC1", 30_000),
            _FakeItem("Same Channel", "UC1", 30_000),
            _FakeItem("Other Channel", "UC2", 100_000),
        ],
    })

    estimator = EcosystemEstimator(adapter, session)
    run = await estimator.estimate(campaign.id)

    assert run.stats["extra"]["results"][0]["total_creators"] == 2


@pytest.mark.asyncio
async def test_no_follower_count_excluded_from_band(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, cn = await _setup_verified_niche(session, "Sim Racing")

    adapter = FakeSearchAdapter({
        "Sim Racing": [
            _FakeItem("Chan A", "UC1", None),
            _FakeItem("Chan B", "UC2", 50_000),
        ],
    })

    estimator = EcosystemEstimator(adapter, session)
    run = await estimator.estimate(campaign.id)

    r = run.stats["extra"]["results"][0]
    assert r["total_creators"] == 2
    assert r["target_band_creators"] == 1


@pytest.mark.asyncio
async def test_multiple_niches(clean_db: AsyncSession):
    session = clean_db
    campaign, _, _ = await _setup_verified_niche(session, "Niche Alpha")
    await _setup_verified_niche(session, "Niche Beta", campaign=campaign)

    adapter = FakeSearchAdapter({
        "Niche Alpha": [_FakeItem("A", "UC1", 20_000)],
        "Niche Beta": [
            _FakeItem("B", "UC2", 50_000),
            _FakeItem("C", "UC3", 80_000),
        ],
    })

    estimator = EcosystemEstimator(adapter, session)
    run = await estimator.estimate(campaign.id)

    assert run.stats["extra"]["niches_checked"] == 2
    totals = {r["niche"]: r["total_creators"] for r in run.stats["extra"]["results"]}
    assert totals["Niche Alpha"] == 1
    assert totals["Niche Beta"] == 2


@pytest.mark.asyncio
async def test_empty_campaign_completes(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Empty")
    session.add(campaign)
    await session.flush()

    adapter = FakeSearchAdapter({})
    estimator = EcosystemEstimator(adapter, session)
    run = await estimator.estimate(campaign.id)

    assert run.status == "completed"
    assert run.stats["extra"]["niches_checked"] == 0


@pytest.mark.asyncio
async def test_skips_non_verified_niches(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.flush()

    niche = Niche(
        canonical_name="Unverified Niche",
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

    adapter = FakeSearchAdapter({"Unverified": [_FakeItem("A", "UC1", 50_000)]})
    estimator = EcosystemEstimator(adapter, session)
    run = await estimator.estimate(campaign.id)

    assert run.stats["extra"]["niches_checked"] == 0


@pytest.mark.asyncio
async def test_search_empty_results(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, cn = await _setup_verified_niche(session, "Obscure Topic")

    adapter = FakeSearchAdapter({"Obscure Topic": []})
    estimator = EcosystemEstimator(adapter, session)
    run = await estimator.estimate(campaign.id)

    assert run.stats["extra"]["results"][0]["total_creators"] == 0
    await session.refresh(cn)
    assert cn.creator_count_observed == 0
    assert cn.target_band_creator_count == 0
