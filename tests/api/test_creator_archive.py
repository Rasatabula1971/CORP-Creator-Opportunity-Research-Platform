"""Archive/unarchive a creator (R14): a reversible "hide from the working
list" independent of the append-only evidence trail (R3) and of
CreatorStatus's state machine. Nothing is ever deleted."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from corp.api.app import create_app
from corp.core.models.creator import Creator, CreatorStatus
from corp.database import get_session


def _make_client(session: AsyncSession) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_creator(session: AsyncSession, name: str) -> Creator:
    creator = Creator(name=name, discovery_source="test", status=CreatorStatus.DISCOVERED)
    session.add(creator)
    await session.commit()
    return creator


@pytest.mark.asyncio
async def test_archive_hides_from_default_list_but_not_include_archived(
    clean_db: AsyncSession,
):
    session = clean_db
    creator = await _make_creator(session, "Archive Me")

    async with _make_client(session) as client:
        resp = await client.post(f"/creators/{creator.id}/archive")
        assert resp.status_code == 200
        body = resp.json()
        assert body["archived_at"] is not None

        default_list = (await client.get("/creators")).json()
        assert creator.id not in {c["id"] for c in default_list}

        full_list = (await client.get("/creators?include_archived=true")).json()
        assert creator.id in {c["id"] for c in full_list}

    await session.refresh(creator)
    assert creator.archived_at is not None
    # Status (the state machine's own field) is untouched by archiving.
    assert creator.status == CreatorStatus.DISCOVERED


@pytest.mark.asyncio
async def test_archive_is_idempotent(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session, "Archive Twice")

    async with _make_client(session) as client:
        first = (await client.post(f"/creators/{creator.id}/archive")).json()
        second = (await client.post(f"/creators/{creator.id}/archive")).json()

    assert first["archived_at"] == second["archived_at"]


@pytest.mark.asyncio
async def test_unarchive_restores_visibility(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session, "Restore Me")

    async with _make_client(session) as client:
        await client.post(f"/creators/{creator.id}/archive")
        resp = await client.post(f"/creators/{creator.id}/unarchive")
        assert resp.status_code == 200
        assert resp.json()["archived_at"] is None

        default_list = (await client.get("/creators")).json()
        assert creator.id in {c["id"] for c in default_list}


@pytest.mark.asyncio
async def test_archive_unknown_creator_404s(clean_db: AsyncSession):
    async with _make_client(clean_db) as client:
        resp = await client.post("/creators/does-not-exist/archive")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_filter_still_composes_with_archived_default(clean_db: AsyncSession):
    """Archiving must not interfere with the existing status/min_score filters."""
    session = clean_db
    visible = await _make_creator(session, "Visible Human Review")
    visible.status = CreatorStatus.HUMAN_REVIEW
    archived = await _make_creator(session, "Archived Human Review")
    archived.status = CreatorStatus.HUMAN_REVIEW
    await session.commit()

    async with _make_client(session) as client:
        await client.post(f"/creators/{archived.id}/archive")
        rows = (await client.get("/creators?status=human_review")).json()

    ids = {r["id"] for r in rows}
    assert visible.id in ids and archived.id not in ids
