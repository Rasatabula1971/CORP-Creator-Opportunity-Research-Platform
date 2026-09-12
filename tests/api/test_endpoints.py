"""API endpoint tests against real Postgres."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from corp.api.app import create_app
from corp.core.models.competitive import Competitor, CompetitorStrength, CompetitorType
from corp.core.models.creator import Creator, CreatorPlatformAccount, CreatorStatus
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal, SignalLevel
from corp.core.models.scoring import ConfidenceBand, CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun
from corp.database import get_session


async def _seed(session: AsyncSession) -> Creator:
    creator = Creator(
        name="APITest",
        niche="tech",
        discovery_source="manual",
        status=CreatorStatus.HUMAN_REVIEW,
    )
    session.add(creator)
    await session.flush()

    acct = CreatorPlatformAccount(
        creator_id=creator.id,
        platform="youtube",
        handle="@apitest",
        subscriber_count=100_000,
    )
    session.add(acct)

    run = ResearchRun(
        creator_id=creator.id,
        status="completed",
        config_snapshot={"pipeline": "scoring"},
        prompt_versions={},
        model_versions={},
    )
    session.add(run)
    await session.flush()

    ev = Evidence(
        source_type="comment",
        source_id="api_cmt_1",
        source_platform="youtube",
        raw_text="Test evidence comment",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        research_run_id=run.id,
    )
    session.add(ev)
    await session.flush()

    cluster = ProblemCluster(
        label="API Problem",
        description="Test cluster",
        frequency=10,
        recency_score=0.7,
        evidence_strength=0.6,
        model_version="test",
    )
    session.add(cluster)
    await session.flush()

    obs = ProblemObservation(
        evidence_id=ev.id,
        text="Test observation",
        category="problem",
        is_inferred=False,
        extraction_prompt_version="extract_v1",
        model_version="test",
        confidence=0.9,
    )
    session.add(obs)
    await session.flush()

    member = ProblemClusterMember(
        cluster_id=cluster.id,
        observation_id=obs.id,
        similarity_score=0.9,
    )
    session.add(member)

    signal_ev = Evidence(
        source_type="intent_classification",
        source_id=cluster.id,
        source_platform="gemini",
        raw_text="Strong intent",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        research_run_id=run.id,
    )
    session.add(signal_ev)
    await session.flush()

    signal = CommercialSignal(
        problem_cluster_id=cluster.id,
        signal_level=SignalLevel.STRONG,
        evidence_id=signal_ev.id,
        rationale="Strong intent detected",
        confidence=0.85,
        classification_model="test",
        prompt_version="intent_v1",
    )
    session.add(signal)

    opp = OpportunityScore(
        creator_id=creator.id,
        problem_cluster_id=cluster.id,
        component_scores={"audience_problem_frequency": 0.6},
        aggregate_score=0.65,
        computed_hash="x" * 64,
        confidence_band=ConfidenceBand.MEDIUM,
        rule_version="scoring_v1",
        model_version="deterministic",
        research_run_id=run.id,
    )
    session.add(opp)

    cs = CreatorScore(
        creator_id=creator.id,
        component_scores={"audience_problem_frequency": 0.6},
        aggregate_score=0.65,
        computed_hash="y" * 64,
        confidence_band=ConfidenceBand.MEDIUM,
        rule_version="scoring_v1",
        model_version="deterministic",
        research_run_id=run.id,
    )
    session.add(cs)

    competitor = Competitor(
        problem_cluster_id=cluster.id,
        name="API Competitor",
        competitor_type=CompetitorType.DIRECT,
        strength=CompetitorStrength.MODERATE,
        gap_notes="Doesn't cover this use case",
    )
    session.add(competitor)
    await session.flush()

    return creator


def _make_client(session: AsyncSession) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_list_creators(clean_db: AsyncSession):
    session = clean_db
    await _seed(session)
    async with _make_client(session) as client:
        resp = await client.get("/creators")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["name"] == "APITest"


@pytest.mark.asyncio
async def test_list_creators_filter_status(clean_db: AsyncSession):
    session = clean_db
    await _seed(session)
    async with _make_client(session) as client:
        resp = await client.get("/creators", params={"status": "human_review"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_list_creators_filter_min_score(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed(session)
    async with _make_client(session) as client:
        resp = await client.get("/creators", params={"min_score": 0.5})
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    async with _make_client(session) as client:
        resp2 = await client.get("/creators", params={"min_score": 0.99})
    assert resp2.status_code == 200
    assert len(resp2.json()) == 0


@pytest.mark.asyncio
async def test_get_creator_detail(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed(session)
    async with _make_client(session) as client:
        resp = await client.get(f"/creators/{creator.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "APITest"
    assert len(data["platform_accounts"]) == 1
    assert data["platform_accounts"][0]["handle"] == "@apitest"


@pytest.mark.asyncio
async def test_get_creator_not_found(clean_db: AsyncSession):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.get("/creators/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_dossier(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed(session)
    async with _make_client(session) as client:
        resp = await client.get(f"/creators/{creator.id}/dossier")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"
    assert "APITest" in resp.text
    assert "<!DOCTYPE html>" in resp.text


@pytest.mark.asyncio
async def test_get_evidence(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed(session)
    async with _make_client(session) as client:
        resp = await client.get(f"/creators/{creator.id}/evidence")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["source_platform"] == "youtube"


@pytest.mark.asyncio
async def test_get_opportunities(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed(session)
    async with _make_client(session) as client:
        resp = await client.get(f"/creators/{creator.id}/opportunities")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["aggregate_score"] == 0.65


@pytest.mark.asyncio
async def test_get_competitors(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed(session)
    async with _make_client(session) as client:
        resp = await client.get(f"/creators/{creator.id}/competitors")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "API Competitor"
    assert data[0]["strength"] == "moderate"


@pytest.mark.asyncio
async def test_get_competitors_not_found(clean_db: AsyncSession):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.get("/creators/nonexistent/competitors")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_decision_approve(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed(session)
    async with _make_client(session) as client:
        resp = await client.post(
            f"/creators/{creator.id}/decisions",
            json={
                "decision": "approve",
                "rationale": "Strong opportunity",
                "decided_by": "test-user",
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["decision"] == "approve"
    assert data["gate"] == "gate_a"
    assert data["rationale"] == "Strong opportunity"


@pytest.mark.asyncio
async def test_create_decision_invalid_state(clean_db: AsyncSession):
    session = clean_db
    creator = Creator(
        name="WrongState",
        niche="test",
        discovery_source="manual",
        status=CreatorStatus.DISCOVERED,
    )
    session.add(creator)
    await session.flush()

    async with _make_client(session) as client:
        resp = await client.post(
            f"/creators/{creator.id}/decisions",
            json={
                "decision": "approve",
            },
        )
    assert resp.status_code == 409
    assert "Cannot transition" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_research_runs(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed(session)
    async with _make_client(session) as client:
        resp = await client.get("/research-runs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_list_research_runs_by_creator(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed(session)
    async with _make_client(session) as client:
        resp = await client.get("/research-runs", params={"creator_id": creator.id})
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["creator_id"] == creator.id for r in data)
