"""API endpoint tests for campaign/niche/creator visibility (Slice 16)."""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from corp.api.app import create_app
from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import Creator
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.niche import Niche, NicheLifecycleStatus
from corp.database import get_session


def _make_client(session: AsyncSession) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_campaign_with_niches(session: AsyncSession) -> Campaign:
    campaign = Campaign(name="API Test Campaign")
    session.add(campaign)
    await session.flush()

    niche_selected = Niche(
        canonical_name="Selected Niche",
        lifecycle_status=NicheLifecycleStatus.ACTIVE,
        last_researched_at=datetime.now(UTC),
    )
    niche_verified = Niche(
        canonical_name="Verified Niche",
        lifecycle_status=NicheLifecycleStatus.ACTIVE,
        last_researched_at=datetime.now(UTC),
    )
    session.add_all([niche_selected, niche_verified])
    await session.flush()

    session.add(CampaignNiche(
        campaign_id=campaign.id, niche_id=niche_selected.id,
        status=CampaignNicheStatus.SELECTED, qualification_score=0.8,
    ))
    session.add(CampaignNiche(
        campaign_id=campaign.id, niche_id=niche_verified.id,
        status=CampaignNicheStatus.VERIFIED, qualification_score=0.4,
    ))
    await session.flush()

    creator = Creator(name="Onboarded Creator", discovery_source="test")
    session.add(creator)
    await session.flush()
    session.add(CreatorNiche(creator_id=creator.id, niche_id=niche_selected.id))
    await session.flush()

    return campaign


@pytest.mark.asyncio
async def test_list_campaigns(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed_campaign_with_niches(session)
    await session.commit()

    async with _make_client(session) as client:
        resp = await client.get("/campaigns")
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert campaign.id in ids


@pytest.mark.asyncio
async def test_get_campaign(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed_campaign_with_niches(session)
    await session.commit()

    async with _make_client(session) as client:
        resp = await client.get(f"/campaigns/{campaign.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "API Test Campaign"


@pytest.mark.asyncio
async def test_get_campaign_not_found(clean_db: AsyncSession):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.get("/campaigns/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_campaign_niches_includes_niche_detail(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed_campaign_with_niches(session)
    await session.commit()

    async with _make_client(session) as client:
        resp = await client.get(f"/campaigns/{campaign.id}/niches")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    # ordered by qualification_score desc
    assert body[0]["niche"]["canonical_name"] == "Selected Niche"
    assert body[0]["qualification_score"] == 0.8


@pytest.mark.asyncio
async def test_list_campaign_niches_filters_by_status(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed_campaign_with_niches(session)
    await session.commit()

    async with _make_client(session) as client:
        resp = await client.get(f"/campaigns/{campaign.id}/niches?status=selected")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["niche"]["canonical_name"] == "Selected Niche"


@pytest.mark.asyncio
async def test_list_campaign_niches_unknown_campaign(clean_db: AsyncSession):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.get("/campaigns/does-not-exist/niches")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_campaign_creators_defaults_to_selected(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed_campaign_with_niches(session)
    await session.commit()

    async with _make_client(session) as client:
        resp = await client.get(f"/campaigns/{campaign.id}/creators")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "Onboarded Creator"


@pytest.mark.asyncio
async def test_list_campaign_creators_niche_status_filter_excludes(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed_campaign_with_niches(session)
    await session.commit()

    async with _make_client(session) as client:
        resp = await client.get(
            f"/campaigns/{campaign.id}/creators?niche_status=verified"
        )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_campaign_creators_unknown_campaign(clean_db: AsyncSession):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.get("/campaigns/does-not-exist/creators")
    assert resp.status_code == 404
