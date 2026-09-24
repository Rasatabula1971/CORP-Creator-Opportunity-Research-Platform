"""API endpoint tests for campaign read (Slice 16) and write (Slice 17)."""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from corp.api.app import create_app
from corp.api.jobs import registry
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
    assert resp.headers["X-Total-Count"] == "1"


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
    assert resp.headers["X-Total-Count"] == "0"


@pytest.mark.asyncio
async def test_list_campaign_creators_unknown_campaign(clean_db: AsyncSession):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.get("/campaigns/does-not-exist/creators")
    assert resp.status_code == 404


# ── Slice 17: Campaign write endpoints ──────────────────────────────


@pytest.mark.asyncio
async def test_create_campaign(clean_db: AsyncSession):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.post(
            "/campaigns",
            json={"name": "New Campaign", "target_niche_count": 5},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "New Campaign"
    assert body["target_niche_count"] == 5
    assert body["status"] == "draft"
    assert body["id"]


@pytest.mark.asyncio
async def test_create_campaign_defaults(clean_db: AsyncSession):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.post("/campaigns", json={"name": "Defaults"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["target_niche_count"] == 10
    assert body["initial_creators_per_niche"] == 10
    assert body["creator_min_followers"] == 10000
    assert body["creator_max_followers"] == 200000


@pytest.mark.asyncio
async def test_create_campaign_rejects_an_inverted_follower_band(clean_db: AsyncSession):
    """Audit fix: the numbers on a campaign now drive every automated
    stage, so an impossible band must be refused at the door rather than
    stored and silently onboarding nobody."""
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.post(
            "/campaigns",
            json={"name": "Inverted", "creator_min_followers": 90_000,
                  "creator_max_followers": 20_000},
        )
    assert resp.status_code == 422
    assert "creator_min_followers must not exceed creator_max_followers" in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field, value",
    [("target_niche_count", 0), ("initial_creators_per_niche", 0), ("human_gate_capacity", 0)],
)
async def test_create_campaign_rejects_zero_work_counts(
    clean_db: AsyncSession, field: str, value: int,
):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.post("/campaigns", json={"name": "Zero", field: value})
    assert resp.status_code == 422
    assert field in resp.text


@pytest.mark.asyncio
async def test_start_campaign_pipeline_unknown_stage(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.commit()

    async with _make_client(session) as client:
        resp = await client.post(f"/campaigns/{campaign.id}/bogus", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_campaign_pipeline_not_found(clean_db: AsyncSession):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.post("/campaigns/does-not-exist/discover", json={})
    assert resp.status_code == 422 or resp.status_code == 404


@pytest.mark.asyncio
async def test_start_discover_requires_query(clean_db: AsyncSession):
    """CORP1 Stage 5, T4: discover no longer needs a platform -- the
    recursive discovery engine fans out across every relevant source
    automatically. Only the broad topic (query) is required now."""
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.commit()

    async with _make_client(session) as client:
        resp = await client.post(
            f"/campaigns/{campaign.id}/discover", json={}
        )
    assert resp.status_code == 422
    assert "requires query" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_campaign_pipeline_conflict(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Test")
    session.add(campaign)
    await session.commit()

    registry.create("verify", campaign_id=campaign.id)

    async with _make_client(session) as client:
        resp = await client.post(
            f"/campaigns/{campaign.id}/verify", json={}
        )
    assert resp.status_code == 409
