"""API: the micro-niche approval queue."""

import itertools

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from corp.api import routes_ops
from corp.api.app import create_app
from corp.api.jobs import JobRegistry
from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.intelligence import ProblemCluster
from corp.core.models.micro_niche import MicroNicheStatus, MicroNicheSuggestion
from corp.workers.providers.factory import ProviderConfigError

_n = itertools.count()


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


@pytest.fixture
def drills(monkeypatch):
    """Fake registry + discovery work, and a provider that 'exists'."""
    registry = JobRegistry()
    monkeypatch.setattr(routes_ops, "registry", registry)
    calls: list[dict] = []

    async def _fake_scan(topics=None, topics_per_pass=None, campaign_id=None):
        calls.append({"topics": topics, "campaign_id": campaign_id})
        return {"topics_drilled": len(topics or [])}

    class _Provider:
        async def close(self):
            pass

    monkeypatch.setattr(routes_ops, "run_discovery_scan", _fake_scan)
    monkeypatch.setattr(routes_ops, "build_provider", lambda: _Provider())
    return calls


async def _seed(session, label="Finishing outdoor oak", frequency=6, followers=40_000):
    c = Creator(name=f"C{next(_n)}", niche="woodworking")
    session.add(c)
    await session.flush()
    session.add(CreatorPlatformAccount(
        creator_id=c.id, platform="youtube", handle=f"@c{next(_n)}", subscriber_count=followers,
    ))
    session.add(ProblemCluster(creator_id=c.id, label=label, frequency=frequency))
    await session.commit()
    return c


async def _suggest_one(client, session, **kw) -> dict:
    await _seed(session, **kw)
    assert (await client.post("/micro-niches/suggest")).status_code == 200
    return (await client.get("/micro-niches")).json()[0]


# ── Queue ────────────────────────────────────────────────────────────


async def test_suggest_then_list(client, clean_db):
    await _seed(clean_db)
    stats = (await client.post("/micro-niches/suggest")).json()
    assert stats["created"] == 1

    resp = await client.get("/micro-niches")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "1"
    [item] = resp.json()
    assert item["label"] == "Finishing outdoor oak"
    assert item["status"] == "pending"
    assert item["follower_count"] == 40_000


async def test_queue_is_ordered_by_breadth_then_frequency(client, clean_db):
    await _seed(clean_db, label="Rare but frequent", frequency=40)
    await _seed(clean_db, label="Everywhere", frequency=3)
    await _seed(clean_db, label="Everywhere", frequency=3)
    await client.post("/micro-niches/suggest")
    labels = [i["label"] for i in (await client.get("/micro-niches")).json()]
    assert labels == ["Everywhere", "Rare but frequent"]


async def test_suggest_for_unknown_creator_is_404(client, clean_db):
    resp = await client.post("/micro-niches/suggest", json={"creator_id": "nope"})
    assert resp.status_code == 404


# ── Approve ──────────────────────────────────────────────────────────


async def test_approve_starts_a_drill_of_the_label(client, clean_db, drills):
    item = await _suggest_one(client, clean_db)
    resp = await client.post(
        f"/micro-niches/{item['id']}/approve", json={"decided_by": "ricky", "note": "go"}
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["suggestion"]["status"] == "approved"
    assert body["suggestion"]["approved_topic"] == "Finishing outdoor oak"
    assert body["suggestion"]["decided_by"] == "ricky"
    assert body["job"]["kind"] == "discovery"
    assert body["suggestion"]["discovery_job_id"] == body["job"]["id"]
    assert drills == [{"topics": ["Finishing outdoor oak"], "campaign_id": None}]


async def test_approve_can_reword_the_topic(client, clean_db, drills):
    item = await _suggest_one(client, clean_db, label="How do I stop outdoor oak going grey")
    resp = await client.post(
        f"/micro-niches/{item['id']}/approve", json={"topic": "  outdoor   wood finishing "}
    )
    assert resp.status_code == 202
    assert resp.json()["suggestion"]["approved_topic"] == "outdoor wood finishing"
    assert drills[0]["topics"] == ["outdoor wood finishing"]


async def test_a_reworded_topic_still_faces_the_exclusion_rules(client, clean_db, drills):
    item = await _suggest_one(client, clean_db)
    resp = await client.post(
        f"/micro-niches/{item['id']}/approve", json={"topic": "sports betting systems"}
    )
    assert resp.status_code == 422
    assert "exclusion" in resp.json()["detail"]
    assert drills == []
    still = (await client.get("/micro-niches")).json()[0]
    assert still["status"] == "pending"


async def test_approve_without_an_llm_leaves_the_suggestion_pending(
    client, clean_db, drills, monkeypatch
):
    """Recording 'approved' behind a job that can never run would strand
    the suggestion: approved rows cannot be approved again."""

    def _no_provider():
        raise ProviderConfigError("No LLM provider configured")

    monkeypatch.setattr(routes_ops, "build_provider", _no_provider)
    item = await _suggest_one(client, clean_db)
    resp = await client.post(f"/micro-niches/{item['id']}/approve")
    assert resp.status_code == 503
    assert drills == []
    row = await clean_db.get(MicroNicheSuggestion, item["id"])
    await clean_db.refresh(row)
    assert row.status == MicroNicheStatus.PENDING


async def test_approving_twice_is_a_conflict(client, clean_db, drills):
    item = await _suggest_one(client, clean_db)
    assert (await client.post(f"/micro-niches/{item['id']}/approve")).status_code == 202
    resp = await client.post(f"/micro-niches/{item['id']}/approve")
    assert resp.status_code == 409
    assert len(drills) == 1


async def test_approve_blank_topic_is_422(client, clean_db, drills):
    item = await _suggest_one(client, clean_db)
    resp = await client.post(f"/micro-niches/{item['id']}/approve", json={"topic": "   "})
    assert resp.status_code == 422


async def test_approve_unknown_is_404(client, clean_db, drills):
    assert (await client.post("/micro-niches/nope/approve")).status_code == 404


async def test_approve_into_unknown_campaign_is_404(client, clean_db, drills):
    item = await _suggest_one(client, clean_db)
    resp = await client.post(
        f"/micro-niches/{item['id']}/approve", json={"campaign_id": "no-such-campaign"}
    )
    assert resp.status_code == 404
    assert drills == []


# ── Reject ───────────────────────────────────────────────────────────


async def test_reject_is_recorded_and_sticks(client, clean_db, drills):
    item = await _suggest_one(client, clean_db)
    resp = await client.post(
        f"/micro-niches/{item['id']}/reject", json={"note": "too broad", "decided_by": "ricky"}
    )
    assert resp.status_code == 200
    assert resp.json()["suggestion"]["status"] == "rejected"
    assert resp.json()["suggestion"]["decision_note"] == "too broad"
    assert drills == [], "rejecting must never drill"

    # A later suggestion run finds the same problem again: it stays rejected.
    await _seed(clean_db, label="Finishing outdoor oak", frequency=99)
    stats = (await client.post("/micro-niches/suggest")).json()
    assert stats["skipped_already_decided"] == 1
    assert (await client.get("/micro-niches")).json() == []
    rejected = (await client.get("/micro-niches", params={"status": "rejected"})).json()
    assert len(rejected) == 1


async def test_reject_after_approve_is_a_conflict(client, clean_db, drills):
    item = await _suggest_one(client, clean_db)
    await client.post(f"/micro-niches/{item['id']}/approve")
    assert (await client.post(f"/micro-niches/{item['id']}/reject")).status_code == 409


async def test_extra_fields_are_rejected(client, clean_db, drills):
    item = await _suggest_one(client, clean_db)
    resp = await client.post(f"/micro-niches/{item['id']}/approve", json={"auto": True})
    assert resp.status_code == 422


# ── Automatic refresh after research ─────────────────────────────────


async def test_research_job_refreshes_the_queue(clean_db, monkeypatch):
    from corp.api import jobs

    c = await _seed(clean_db, label="Clamping odd shapes")
    result = await jobs._refresh_micro_niches(c.id)
    assert result is not None and result["created"] == 1
    rows = (await clean_db.execute(select(MicroNicheSuggestion))).scalars().all()
    assert [r.label for r in rows] == ["Clamping odd shapes"]


async def test_a_refresh_failure_never_fails_research(monkeypatch):
    from corp.api import jobs
    from corp.workers.intelligence import micro_niches

    class _Broken:
        def __init__(self, *a, **kw):
            raise RuntimeError("seeder exploded")

    monkeypatch.setattr(micro_niches, "MicroNicheSeeder", _Broken)
    assert await jobs._refresh_micro_niches("any") is None
