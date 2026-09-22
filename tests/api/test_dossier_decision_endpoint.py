"""API tests for the dossier-level four-state decision gate (CORP1 Stage
5, T8): POST /dossiers/{dossier_id}/decision. One test per decision
outcome (Reject / Research More / Watch / Approve), asserting the
correct downstream effect, plus a test that HumanDecision stays
append-only across repeated decisions on the same dossier."""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import corp.api.routes_ops as routes_ops
from corp.api.app import create_app
from corp.api.jobs import registry
from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.dossier import Dossier, DossierStatus
from corp.core.models.intelligence import ProblemCluster
from corp.core.models.niche import Niche
from corp.core.models.scoring import ConfidenceBand, OpportunityScore
from corp.core.models.workflow import HumanDecision
from corp.database import get_session


def _make_client(session: AsyncSession) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_dossier(
    session: AsyncSession,
    *,
    with_campaign: bool = False,
    creator_status: CreatorStatus = CreatorStatus.HUMAN_REVIEW,
) -> Dossier:
    # HUMAN_REVIEW is where a real creator sits when its dossier is decided,
    # so the R12b creator-status mirror takes its normal path in every test.
    creator = Creator(
        name="Decision Gate Creator", discovery_source="test", status=creator_status
    )
    session.add(creator)
    await session.flush()

    niche = Niche(canonical_name="Home Espresso T8", depth=0)
    session.add(niche)
    await session.flush()

    cluster = ProblemCluster(
        creator_id=creator.id, label="Grinder confusion", frequency=3, evidence_strength=0.8
    )
    session.add(cluster)
    await session.flush()

    opp = OpportunityScore(
        creator_id=creator.id,
        problem_cluster_id=cluster.id,
        component_scores={"frequency": 0.7},
        aggregate_score=0.7,
        computed_hash="hash-t8",
        confidence_band=ConfidenceBand.HIGH,
        rule_version="v1.0.0",
        model_version="fixture",
    )
    session.add(opp)
    await session.flush()

    if with_campaign:
        campaign = Campaign(name="T8 Test Campaign")
        session.add(campaign)
        await session.flush()
        session.add(
            CampaignNiche(
                campaign_id=campaign.id,
                niche_id=niche.id,
                status=CampaignNicheStatus.SELECTED,
            )
        )
        await session.flush()

    dossier = Dossier(
        creator_id=creator.id,
        niche_id=niche.id,
        opportunity_score_id=opp.id,
        content={"score_band": "Strong opportunity"},
    )
    session.add(dossier)
    await session.commit()
    return dossier


@pytest.mark.asyncio
async def test_reject_sets_dossier_rejected(clean_db: AsyncSession):
    session = clean_db
    dossier = await _seed_dossier(session)

    async with _make_client(session) as client:
        resp = await client.post(
            f"/dossiers/{dossier.id}/decision",
            json={"decision": "reject", "rationale": "Too niche"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["decision"] == "reject"
    assert body["dossier_status"] == "rejected"
    assert body["job_id"] is None

    await session.refresh(dossier)
    assert dossier.status == DossierStatus.REJECTED


@pytest.mark.asyncio
async def test_watch_sets_dossier_watching_with_no_other_side_effect(clean_db: AsyncSession):
    session = clean_db
    dossier = await _seed_dossier(session)

    async with _make_client(session) as client:
        resp = await client.post(
            f"/dossiers/{dossier.id}/decision", json={"decision": "watch"}
        )
    assert resp.status_code == 201
    assert resp.json()["dossier_status"] == "watching"
    assert resp.json()["job_id"] is None

    await session.refresh(dossier)
    assert dossier.status == DossierStatus.WATCHING


@pytest.mark.asyncio
async def test_approve_sets_dossier_approved(clean_db: AsyncSession):
    session = clean_db
    dossier = await _seed_dossier(session)

    async with _make_client(session) as client:
        resp = await client.post(
            f"/dossiers/{dossier.id}/decision", json={"decision": "approve"}
        )
    assert resp.status_code == 201
    assert resp.json()["dossier_status"] == "approved"
    assert resp.json()["job_id"] is None

    await session.refresh(dossier)
    assert dossier.status == DossierStatus.APPROVED


@pytest.mark.asyncio
async def test_research_more_starts_a_job_and_sets_in_progress(
    clean_db: AsyncSession, monkeypatch
):
    session = clean_db
    dossier = await _seed_dossier(session, with_campaign=True)

    calls: list[tuple[str, str, str]] = []

    async def _fake_run_research_more(
        dossier_id: str, niche_id: str, campaign_id: str
    ) -> dict[str, Any]:
        calls.append((dossier_id, niche_id, campaign_id))
        return {"run_id": "fake-run", "status": "completed", "stats": {}}

    monkeypatch.setattr(routes_ops, "_run_research_more", _fake_run_research_more)

    campaign_niche = (
        await session.execute(
            select(CampaignNiche).where(CampaignNiche.niche_id == dossier.niche_id)
        )
    ).scalar_one()

    async with _make_client(session) as client:
        resp = await client.post(
            f"/dossiers/{dossier.id}/decision", json={"decision": "research_more"}
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["dossier_status"] == "research_more_in_progress"
    assert body["job_id"] is not None

    await session.refresh(dossier)
    assert dossier.status == DossierStatus.RESEARCH_MORE_IN_PROGRESS
    assert calls == [(dossier.id, dossier.niche_id, campaign_niche.campaign_id)]


@pytest.mark.asyncio
async def test_research_more_without_campaign_association_is_422(clean_db: AsyncSession):
    session = clean_db
    dossier = await _seed_dossier(session, with_campaign=False)

    async with _make_client(session) as client:
        resp = await client.post(
            f"/dossiers/{dossier.id}/decision", json={"decision": "research_more"}
        )
    assert resp.status_code == 422
    assert "campaign association" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_research_more_conflicts_with_active_campaign_job(clean_db: AsyncSession):
    session = clean_db
    dossier = await _seed_dossier(session, with_campaign=True)
    campaign_niche = (
        await session.execute(
            select(CampaignNiche).where(CampaignNiche.niche_id == dossier.niche_id)
        )
    ).scalar_one()
    registry.create("discover", campaign_id=campaign_niche.campaign_id)

    async with _make_client(session) as client:
        resp = await client.post(
            f"/dossiers/{dossier.id}/decision", json={"decision": "research_more"}
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_dossier_not_found_is_404(clean_db: AsyncSession):
    session = clean_db
    async with _make_client(session) as client:
        resp = await client.post(
            "/dossiers/does-not-exist/decision", json={"decision": "approve"}
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invalid_decision_value_is_422(clean_db: AsyncSession):
    session = clean_db
    dossier = await _seed_dossier(session)
    async with _make_client(session) as client:
        resp = await client.post(
            f"/dossiers/{dossier.id}/decision", json={"decision": "maybe"}
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_human_decision_remains_append_only(clean_db: AsyncSession):
    """Two decisions on the same dossier must produce two rows, never an
    update to the first -- HumanDecision is append-only by design."""
    session = clean_db
    dossier = await _seed_dossier(session)

    async with _make_client(session) as client:
        first = await client.post(
            f"/dossiers/{dossier.id}/decision", json={"decision": "watch"}
        )
        second = await client.post(
            f"/dossiers/{dossier.id}/decision", json={"decision": "reject"}
        )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]

    rows = (
        await session.execute(
            select(HumanDecision).where(HumanDecision.dossier_id == dossier.id)
        )
    ).scalars().all()
    assert len(rows) == 2
    assert {r.decision.value for r in rows} == {"watch", "reject"}
    # Final dossier status reflects the most recent decision, but both rows
    # persist unchanged -- the read-cache status field is not the ledger.
    await session.refresh(dossier)
    assert dossier.status == DossierStatus.REJECTED


# ---------- R12b: creator status mirrors the dossier gate ----------


async def _set_creator_status(
    session: AsyncSession, dossier: Dossier, status: CreatorStatus
) -> Creator:
    creator = await session.get(Creator, dossier.creator_id)
    assert creator is not None
    creator.status = status
    await session.commit()
    return creator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        ("watch", CreatorStatus.WATCHING),
        ("approve", CreatorStatus.APPROVED),
        ("reject", CreatorStatus.REJECTED),
    ],
)
async def test_dossier_decision_mirrors_to_creator_status(
    clean_db: AsyncSession, decision: str, expected: CreatorStatus
):
    session = clean_db
    dossier = await _seed_dossier(session)
    creator = await _set_creator_status(session, dossier, CreatorStatus.HUMAN_REVIEW)

    async with _make_client(session) as client:
        resp = await client.post(f"/dossiers/{dossier.id}/decision", json={"decision": decision})
    assert resp.status_code == 201

    await session.refresh(creator)
    assert creator.status == expected


@pytest.mark.asyncio
async def test_watched_creator_can_then_be_approved_from_its_dossier(clean_db: AsyncSession):
    session = clean_db
    dossier = await _seed_dossier(session)
    creator = await _set_creator_status(session, dossier, CreatorStatus.HUMAN_REVIEW)

    async with _make_client(session) as client:
        assert (await client.post(
            f"/dossiers/{dossier.id}/decision", json={"decision": "watch"}
        )).status_code == 201
        assert (await client.post(
            f"/dossiers/{dossier.id}/decision", json={"decision": "approve"}
        )).status_code == 201

    await session.refresh(creator)
    assert creator.status == CreatorStatus.APPROVED


@pytest.mark.asyncio
async def test_pending_dossier_on_another_niche_keeps_creator_in_review(clean_db: AsyncSession):
    """Multi-niche precedence: a watched dossier does not park the creator
    while another of its dossiers still awaits a decision."""
    session = clean_db
    dossier = await _seed_dossier(session)
    creator = await _set_creator_status(session, dossier, CreatorStatus.HUMAN_REVIEW)
    other_niche = Niche(canonical_name="Sourdough T8", depth=0)
    session.add(other_niche)
    await session.flush()
    session.add(Dossier(
        creator_id=creator.id, niche_id=other_niche.id,
        opportunity_score_id=dossier.opportunity_score_id, content={},
    ))
    await session.commit()

    async with _make_client(session) as client:
        resp = await client.post(f"/dossiers/{dossier.id}/decision", json={"decision": "watch"})
    assert resp.status_code == 201

    await session.refresh(creator)
    assert creator.status == CreatorStatus.HUMAN_REVIEW


@pytest.mark.asyncio
async def test_mirror_never_fails_the_decision_for_a_non_gate_creator(
    clean_db: AsyncSession, caplog: pytest.LogCaptureFixture
):
    """A creator not at a gate-adjacent status (fixture default DISCOVERED)
    cannot legally move to WATCHING; the decision still succeeds and the
    creator is left alone, with a warning."""
    session = clean_db
    dossier = await _seed_dossier(session, creator_status=CreatorStatus.DISCOVERED)
    creator = await session.get(Creator, dossier.creator_id)
    assert creator is not None and creator.status == CreatorStatus.DISCOVERED

    async with _make_client(session) as client:
        with caplog.at_level("WARNING", logger="corp.core.state.gates"):
            resp = await client.post(
                f"/dossiers/{dossier.id}/decision", json={"decision": "watch"}
            )
    assert resp.status_code == 201
    await session.refresh(dossier)
    await session.refresh(creator)
    assert dossier.status == DossierStatus.WATCHING
    assert creator.status == CreatorStatus.DISCOVERED
    assert "Not mirroring dossier gate" in caplog.text
