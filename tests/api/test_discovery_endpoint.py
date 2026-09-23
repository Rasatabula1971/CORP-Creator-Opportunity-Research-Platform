"""API tests for POST /discovery/run — both entry points the spec freezes."""

import pytest
from httpx import ASGITransport, AsyncClient

from corp.api import routes_ops
from corp.api.app import create_app
from corp.api.jobs import JobRegistry
from corp.config import settings


@pytest.fixture
def client():
    app = create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def captured(monkeypatch):
    """Swap the registry and the work function so no pipeline actually runs."""
    registry = JobRegistry()
    monkeypatch.setattr(routes_ops, "registry", registry)

    calls: list[dict] = []

    async def _fake_scan(topics=None, topics_per_pass=None, campaign_id=None):
        calls.append(
            {
                "topics": topics,
                "topics_per_pass": topics_per_pass,
                "campaign_id": campaign_id,
            }
        )
        return {"topics_drilled": len(topics or [])}

    monkeypatch.setattr(routes_ops, "run_discovery_scan", _fake_scan)
    return calls


async def test_empty_body_starts_an_autonomous_pass(client, captured):
    resp = await client.post("/discovery/run")
    assert resp.status_code == 202
    body = resp.json()
    assert body["kind"] == "discovery"
    assert body["status"] in ("queued", "running", "completed")


async def test_supplied_topics_are_forwarded(client, captured):
    resp = await client.post("/discovery/run", json={"topics": ["woodworking", "baking"]})
    assert resp.status_code == 202
    assert captured[0]["topics"] == ["woodworking", "baking"]


async def test_blank_topics_are_rejected(client, captured):
    resp = await client.post("/discovery/run", json={"topics": ["   ", ""]})
    assert resp.status_code == 422
    assert "must not be blank" in resp.json()["detail"]
    assert captured == []


async def test_unknown_campaign_is_404(client, captured):
    resp = await client.post("/discovery/run", json={"campaign_id": "no-such-campaign"})
    assert resp.status_code == 404
    assert captured == []


async def test_extra_fields_are_rejected(client, captured):
    resp = await client.post("/discovery/run", json={"nope": 1})
    assert resp.status_code == 422


async def test_topics_per_pass_is_bounded(client, captured):
    assert (await client.post("/discovery/run", json={"topics_per_pass": 0})).status_code == 422
    assert (await client.post("/discovery/run", json={"topics_per_pass": 99})).status_code == 422


async def test_topics_list_is_bounded(client, captured):
    resp = await client.post("/discovery/run", json={"topics": [f"t{i}" for i in range(26)]})
    assert resp.status_code == 422


async def test_discovery_requires_the_api_key_when_one_is_set(client, monkeypatch, captured):
    monkeypatch.setattr(settings, "api_key", "secret")
    resp = await client.post("/discovery/run")
    assert resp.status_code == 401


async def test_the_crawler_is_off_by_default():
    """Installing CORP must not start unattended LLM spend."""
    assert settings.discovery_enabled is False


async def test_blank_topics_per_pass_env_does_not_crash_startup(monkeypatch):
    """Copying .env.example and leaving the override empty must not raise
    an int_parsing error at import, before anything has logged."""
    from corp.config import Settings

    monkeypatch.setenv("DISCOVERY_TOPICS_PER_PASS", "")
    assert Settings().discovery_topics_per_pass is None
    monkeypatch.setenv("DISCOVERY_TOPICS_PER_PASS", "7")
    assert Settings().discovery_topics_per_pass == 7


# ── GET /discovery/status ────────────────────────────────────────────


async def test_status_reports_the_crawler_as_off_by_default(client, clean_db):
    resp = await client.get("/discovery/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["catalogue_size"] > 0
    assert body["topics_per_pass"] >= 1
    # No LLM key in the test environment, so a pass could not actually run.
    assert body["can_run"] is False
    assert body["provider_detail"]


async def test_status_reports_enabled_when_the_setting_is_on(client, clean_db, monkeypatch):
    monkeypatch.setattr(settings, "discovery_enabled", True)
    body = (await client.get("/discovery/status")).json()
    assert body["enabled"] is True


async def test_status_previews_the_topics_the_next_pass_would_take(client, clean_db):
    body = (await client.get("/discovery/status")).json()
    assert body["next_topics"], "a fresh registry should have topics due"
    assert len(body["next_topics"]) == body["topics_per_pass"]
    assert body["scan"]["selected"] == len(body["next_topics"])


async def test_status_hides_topics_already_inside_their_recheck_window(client, clean_db):
    from datetime import UTC, datetime, timedelta

    from corp.core.models.niche import Niche

    first = (await client.get("/discovery/status")).json()["next_topics"][0]
    clean_db.add(
        Niche(
            canonical_name=first,
            last_researched_at=datetime.now(UTC),
            next_recheck_at=datetime.now(UTC) + timedelta(days=90),
        )
    )
    await clean_db.commit()

    body = (await client.get("/discovery/status")).json()
    assert first not in body["next_topics"]
    assert body["scan"]["registry_fresh"] >= 1


async def test_status_never_500s_when_the_preview_scan_breaks(client, clean_db, monkeypatch):
    """A status read is for diagnosing trouble, so it must survive it."""

    class _Broken:
        def __init__(self, *a, **kw):
            raise RuntimeError("catalogue is unreadable")

    monkeypatch.setattr(
        "corp.workers.intelligence.trend_scan.TrendScanner.__init__",
        lambda self, *a, **kw: (_ for _ in ()).throw(RuntimeError("catalogue unreadable")),
    )
    resp = await client.get("/discovery/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "catalogue unreadable" in body["error"]
    assert body["next_topics"] == []
    # The settings half still answers, which is the part you check first.
    assert body["enabled"] is False
    assert body["interval_seconds"] > 0


async def test_status_reports_the_momentum_source(client, clean_db, monkeypatch):
    monkeypatch.setattr(settings, "discovery_momentum_source", "youtube")
    monkeypatch.setattr(settings, "youtube_api_key", "")
    body = (await client.get("/discovery/status")).json()
    assert body["momentum_source"] == "youtube"
    assert body["momentum_available"] is False
    assert "YOUTUBE_API_KEY" in body["momentum_detail"]

    monkeypatch.setattr(settings, "youtube_api_key", "k")
    body = (await client.get("/discovery/status")).json()
    assert body["momentum_available"] is True
    assert body["momentum_detail"] is None


async def test_status_uses_the_configured_catalogue(client, clean_db, monkeypatch, tmp_path):
    custom = tmp_path / "topics.yaml"
    custom.write_text(
        'version: "t"\nscan:\n  topics_per_pass: 2\n  geo: "US"\ntopics:\n  - alpha\n  - beta\n'
    )
    monkeypatch.setattr(settings, "broad_topics_path", str(custom))
    body = (await client.get("/discovery/status")).json()
    assert body["catalogue_size"] == 2
    assert set(body["next_topics"]) == {"alpha", "beta"}
