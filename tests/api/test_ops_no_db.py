"""API tests that need no database: health, auth, error shape, job registry."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from corp.api import jobs as jobs_module
from corp.api.app import create_app
from corp.api.jobs import JobRegistry, JobStatus
from corp.config import settings


@pytest.fixture
def client():
    app = create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    return "secret"


async def test_health_is_open_even_with_api_key(client, api_key):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_missing_api_key_is_401_with_error_shape(client, api_key):
    resp = await client.get("/jobs")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"].startswith("Missing or invalid")
    assert body["error"] == {"code": "unauthorized", "message": body["detail"]}
    assert resp.headers["WWW-Authenticate"] == "ApiKey"


async def test_wrong_api_key_is_401(client, api_key):
    resp = await client.get("/jobs", headers={"X-Api-Key": "nope"})
    assert resp.status_code == 401


async def test_correct_api_key_passes(client, api_key):
    resp = await client.get("/jobs", headers={"X-Api-Key": "secret"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_no_api_key_configured_means_open(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")
    resp = await client.get("/jobs")
    assert resp.status_code == 200


async def test_unknown_job_is_404_with_error_shape(client):
    resp = await client.get("/jobs/doesnotexist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_validation_error_shape(client):
    resp = await client.get("/jobs?limit=notanumber")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["errors"], list)


async def test_registry_lifecycle_and_listing():
    reg = JobRegistry()
    job = reg.create("research", "c1")
    assert job.status == JobStatus.QUEUED
    assert reg.active_for("c1") is job
    assert reg.get(job.id) is job

    async def work():
        return {"ok": True}

    await reg.execute(job, work)
    assert job.status == JobStatus.COMPLETED
    assert job.result == {"ok": True}
    assert job.started_at is not None and job.finished_at is not None
    assert reg.active_for("c1") is None
    assert reg.list(creator_id="c1") == [job]
    assert reg.list(creator_id="other") == []


async def test_registry_records_failure_without_raising():
    reg = JobRegistry()
    job = reg.create("scoring", "c1")

    async def work():
        raise RuntimeError("provider down")

    await reg.execute(job, work)
    assert job.status == JobStatus.FAILED
    # Only the exception type is stored (hardened in the adversarial-audit
    # commit 5d239e2 so internal messages never leak to the API); the full
    # message goes to the log via logger.exception.
    assert job.error == "RuntimeError"
    assert job.result is None


def test_registry_evicts_only_finished_jobs():
    reg = JobRegistry(max_jobs=2)
    a = reg.create("research", "a")
    a.status = JobStatus.COMPLETED
    b = reg.create("research", "b")  # still queued
    reg.create("research", "c")
    assert reg.get(a.id) is None
    assert reg.get(b.id) is not None


async def test_job_endpoint_reflects_registry(client, monkeypatch):
    reg = JobRegistry()
    monkeypatch.setattr(jobs_module, "registry", reg)
    monkeypatch.setattr("corp.api.routes_ops.registry", reg)
    job = reg.create("intent", "c9")
    resp = await client.get(f"/jobs/{job.id}")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "intent" and resp.json()["status"] == "queued"
    resp = await client.get("/jobs", params={"creator_id": "c9"})
    assert [j["id"] for j in resp.json()] == [job.id]


async def test_start_pipeline_rejects_unknown_pipeline_before_touching_db(client):
    resp = await client.post("/creators/c1/runs", json={"pipeline": "nope"})
    assert resp.status_code == 422
    assert "pipeline must be one of" in resp.json()["detail"]


async def test_collect_requires_platform_and_identifier(client):
    resp = await client.post("/creators/c1/runs", json={"pipeline": "collect"})
    assert resp.status_code == 422
    assert "collect requires" in resp.json()["detail"]


async def test_run_pipeline_unknown_kind_raises():
    with pytest.raises(ValueError, match="Unknown pipeline"):
        await jobs_module.run_pipeline("nope", "c1")


def test_event_loop_not_required_for_registry_create():
    # create() is sync so request handlers can call it before scheduling work
    reg = JobRegistry()
    assert reg.create("x", None).creator_id is None
    asyncio.get_event_loop_policy()
