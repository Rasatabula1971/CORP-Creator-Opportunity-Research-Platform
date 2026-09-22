"""Integration tests for CreatorOnboarder against real Postgres."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import CreatorPlatformAccount
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.niche import Niche, NicheLifecycleStatus
from corp.workers.acquisition.creator_onboarding import CreatorOnboarder, OnboardConfig

# ── fake adapter ──────────────────────────────────────────────────────


class _FakeItem:
    def __init__(self, author: str, channel_id: str, follower_count: int | None):
        self.author = author
        self.metadata = {"channel_id": channel_id, "follower_count": follower_count}


class FakeSearchAdapter:
    def __init__(self, results: dict[str, list[_FakeItem]]) -> None:
        self._results = results

    async def collect(self, identifier: str) -> list[_FakeItem]:
        for key, items in self._results.items():
            if key.lower() in identifier.lower():
                return items
        return []


# ── helpers ───────────────────────────────────────────────────────────


async def _setup_selected_niche(
    session: AsyncSession,
    niche_name: str,
    *,
    campaign: Campaign | None = None,
    status: CampaignNicheStatus = CampaignNicheStatus.SELECTED,
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
        campaign_id=campaign.id, niche_id=niche.id, status=status,
    )
    session.add(cn)
    await session.flush()

    return campaign, niche, cn


# ── tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creates_new_creator_and_platform_account(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup_selected_niche(session, "Home Espresso")

    adapter = FakeSearchAdapter({
        "Home Espresso": [_FakeItem("Chan A", "UCaaaaaaaaaaaaaaaaaaaaaa", 50_000)],
    })
    onboarder = CreatorOnboarder(adapter, session)
    run = await onboarder.onboard(campaign.id)

    assert run.status == "completed"
    extra = run.stats["extra"]
    assert extra["creators_created"] == 1
    assert extra["creators_linked"] == 0

    result = await session.execute(
        select(CreatorPlatformAccount).where(
            CreatorPlatformAccount.handle == "UCaaaaaaaaaaaaaaaaaaaaaa",
        )
    )
    account = result.scalar_one()
    assert account.platform == "youtube"
    assert account.subscriber_count == 50_000


@pytest.mark.asyncio
async def test_links_existing_creator_by_platform_handle(clean_db: AsyncSession):
    session = clean_db
    campaign, niche_a, _ = await _setup_selected_niche(session, "Niche A")
    _, niche_b, _ = await _setup_selected_niche(
        session, "Niche B", campaign=campaign,
    )

    adapter = FakeSearchAdapter({
        "Niche A": [_FakeItem("Shared Chan", "UCbbbbbbbbbbbbbbbbbbbbbb", 30_000)],
        "Niche B": [_FakeItem("Shared Chan", "UCbbbbbbbbbbbbbbbbbbbbbb", 30_000)],
    })
    onboarder = CreatorOnboarder(adapter, session)
    run = await onboarder.onboard(campaign.id)

    extra = run.stats["extra"]
    assert extra["creators_created"] == 1
    assert extra["creators_linked"] == 1

    result = await session.execute(
        select(CreatorPlatformAccount).where(
            CreatorPlatformAccount.handle == "UCbbbbbbbbbbbbbbbbbbbbbb",
        )
    )
    accounts = result.scalars().all()
    assert len(accounts) == 1


@pytest.mark.asyncio
async def test_creates_creator_niche_association(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup_selected_niche(session, "Reef Aquarium")

    adapter = FakeSearchAdapter({
        "Reef Aquarium": [_FakeItem("Chan", "UCcccccccccccccccccccccc", 20_000)],
    })
    onboarder = CreatorOnboarder(adapter, session)
    await onboarder.onboard(campaign.id)

    result = await session.execute(
        select(CreatorNiche).where(CreatorNiche.niche_id == niche.id)
    )
    link = result.scalar_one()
    assert link.discovery_run_id is not None


@pytest.mark.asyncio
async def test_rerun_updates_last_observed_at_without_duplicating(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup_selected_niche(session, "Sim Racing")

    adapter = FakeSearchAdapter({
        "Sim Racing": [_FakeItem("Chan", "UCdddddddddddddddddddddd", 40_000)],
    })
    onboarder = CreatorOnboarder(adapter, session)
    await onboarder.onboard(campaign.id)
    first_run = await onboarder.onboard(campaign.id)

    assert first_run.stats["extra"]["creators_created"] == 0
    assert first_run.stats["extra"]["creators_linked"] == 1

    result = await session.execute(
        select(CreatorNiche).where(CreatorNiche.niche_id == niche.id)
    )
    links = result.scalars().all()
    assert len(links) == 1


@pytest.mark.asyncio
async def test_respects_max_creators_per_niche(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup_selected_niche(session, "Obscure Topic")

    items = [
        _FakeItem(f"Chan {i}", f"UC{'x' * 21}{i:02d}", 10_000 + i)
        for i in range(5)
    ]
    adapter = FakeSearchAdapter({"Obscure Topic": items})
    onboarder = CreatorOnboarder(adapter, session, OnboardConfig(max_creators_per_niche=2))
    run = await onboarder.onboard(campaign.id)

    assert run.stats["extra"]["creators_created"] == 2


@pytest.mark.asyncio
async def test_skips_non_selected_niches(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup_selected_niche(
        session, "Unverified", status=CampaignNicheStatus.VERIFIED,
    )

    adapter = FakeSearchAdapter({
        "Unverified": [_FakeItem("Chan", "UCeeeeeeeeeeeeeeeeeeeeee", 10_000)],
    })
    onboarder = CreatorOnboarder(adapter, session)
    run = await onboarder.onboard(campaign.id)

    assert run.stats["extra"]["niches_processed"] == 0
    assert run.stats["extra"]["creators_created"] == 0


@pytest.mark.asyncio
async def test_empty_campaign(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Empty")
    session.add(campaign)
    await session.flush()

    adapter = FakeSearchAdapter({})
    onboarder = CreatorOnboarder(adapter, session)
    run = await onboarder.onboard(campaign.id)

    assert run.status == "completed"
    assert run.stats["extra"]["niches_processed"] == 0


@pytest.mark.asyncio
async def test_dedupes_within_single_search_results(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup_selected_niche(session, "Dedup Niche")

    adapter = FakeSearchAdapter({
        "Dedup Niche": [
            _FakeItem("Chan", "UCffffffffffffffffffffff", 10_000),
            _FakeItem("Chan", "UCffffffffffffffffffffff", 10_000),
        ],
    })
    onboarder = CreatorOnboarder(adapter, session)
    run = await onboarder.onboard(campaign.id)

    assert run.stats["extra"]["creators_created"] == 1


@pytest.mark.asyncio
async def test_follower_band_filter(clean_db: AsyncSession):
    session = clean_db
    campaign, niche, _ = await _setup_selected_niche(session, "Banded Niche")

    adapter = FakeSearchAdapter({
        "Banded Niche": [
            _FakeItem("Too Small", "UCgggggggggggggggggggggg", 100),
            _FakeItem("Just Right", "UChhhhhhhhhhhhhhhhhhhhhh", 50_000),
            _FakeItem("Too Big", "UCiiiiiiiiiiiiiiiiiiiiii", 5_000_000),
            _FakeItem("Unknown", "UCjjjjjjjjjjjjjjjjjjjjjj", None),
        ],
    })
    onboarder = CreatorOnboarder(
        adapter, session,
        OnboardConfig(min_followers=10_000, max_followers=200_000),
    )
    run = await onboarder.onboard(campaign.id)

    # "Just Right" and "Unknown" (unknown reach never blocks) pass the filter
    assert run.stats["extra"]["creators_created"] == 2


@pytest.mark.asyncio
async def test_multiple_niches_in_one_run(clean_db: AsyncSession):
    session = clean_db
    campaign, _, _ = await _setup_selected_niche(session, "Niche Alpha")
    _, _, _ = await _setup_selected_niche(session, "Niche Beta", campaign=campaign)

    adapter = FakeSearchAdapter({
        "Niche Alpha": [_FakeItem("A", "UCkkkkkkkkkkkkkkkkkkkkkk", 10_000)],
        "Niche Beta": [_FakeItem("B", "UClllllllllllllllllllll", 20_000)],
    })
    onboarder = CreatorOnboarder(adapter, session)
    run = await onboarder.onboard(campaign.id)

    assert run.stats["extra"]["niches_processed"] == 2
    assert run.stats["extra"]["creators_created"] == 2


@pytest.mark.asyncio
async def test_skips_excluded_niche_even_if_selected(clean_db: AsyncSession):
    """R5: a niche moved to EXCLUDED after selection must not onboard creators."""
    session = clean_db
    campaign, niche, _ = await _setup_selected_niche(session, "Sports Betting Odds")
    niche.lifecycle_status = NicheLifecycleStatus.EXCLUDED
    await session.flush()

    adapter = FakeSearchAdapter({
        "Sports Betting Odds": [_FakeItem("Chan", "UCeeeeeeeeeeeeeeeeeeeeee", 10_000)],
    })
    onboarder = CreatorOnboarder(adapter, session)
    run = await onboarder.onboard(campaign.id)

    assert run.stats["extra"]["niches_processed"] == 0
    assert run.stats["extra"]["creators_created"] == 0
