"""API tests for GET /dossiers/{dossier_id}/handoff — the CORP2 handoff
package endpoint that wires T9's build_handoff_package to a pull API."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from corp.api.app import create_app
from corp.core.models.creator import Creator
from corp.core.models.dossier import Dossier, DossierEvidence, DossierStatus
from corp.core.models.evidence import (
    AccessMethod,
    ComplianceStatus,
    Evidence,
    EvidenceOrigin,
    EvidenceType,
)
from corp.core.models.intelligence import ProblemCluster
from corp.core.models.niche import Niche
from corp.core.models.scoring import ConfidenceBand, OpportunityScore
from corp.core.models.workflow import DecisionType, Gate, HumanDecision
from corp.database import get_session


def _make_client(session: AsyncSession) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_approved_dossier(session: AsyncSession) -> Dossier:
    niche = Niche(canonical_name="handoff-test-niche", depth=0)
    session.add(niche)
    await session.flush()

    creator = Creator(name="Handoff Creator", discovery_source="test")
    session.add(creator)
    await session.flush()

    cluster = ProblemCluster(
        creator_id=creator.id, label="Widget issues", frequency=5, evidence_strength=0.9
    )
    session.add(cluster)
    await session.flush()

    opp = OpportunityScore(
        creator_id=creator.id,
        problem_cluster_id=cluster.id,
        component_scores={"frequency": 0.8},
        aggregate_score=0.8,
        computed_hash="hash-handoff",
        confidence_band=ConfidenceBand.HIGH,
        rule_version="v1",
        model_version="fixture",
    )
    session.add(opp)
    await session.flush()

    dossier = Dossier(
        creator_id=creator.id,
        niche_id=niche.id,
        opportunity_score_id=opp.id,
        content={"summary": "Strong opportunity"},
        status=DossierStatus.APPROVED,
    )
    session.add(dossier)
    await session.flush()

    evidence = Evidence(
        source_type="comment",
        source_id="handoff_ev_1",
        source_platform="youtube",
        raw_text="I need a better widget",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        origin=EvidenceOrigin.OBSERVATION,
        evidence_type=EvidenceType.PROBLEM,
    )
    session.add(evidence)
    await session.flush()

    session.add(DossierEvidence(dossier_id=dossier.id, evidence_id=evidence.id))

    session.add(
        HumanDecision(
            creator_id=creator.id,
            dossier_id=dossier.id,
            decision=DecisionType.APPROVE,
            gate=Gate.GATE_D,
            rationale="Looks great, proceed to partnership",
            decided_by="reviewer",
        )
    )
    await session.commit()
    return dossier


@pytest.mark.asyncio
async def test_handoff_returns_package_for_approved_dossier(clean_db: AsyncSession):
    session = clean_db
    dossier = await _seed_approved_dossier(session)

    async with _make_client(session) as client:
        resp = await client.get(f"/dossiers/{dossier.id}/handoff")

    assert resp.status_code == 200
    body = resp.json()
    assert body["dossier_id"] == dossier.id
    assert body["dossier_status"] == "approved"
    assert body["decision_notes"] == "Looks great, proceed to partnership"
    assert len(body["evidence_trail"]) == 1
    assert body["evidence_trail"][0]["raw_text"] == "I need a better widget"
    assert len(body["niche_path"]) == 1
    assert body["niche_path"][0]["canonical_name"] == "handoff-test-niche"


@pytest.mark.asyncio
async def test_handoff_rejects_non_approved_dossier(clean_db: AsyncSession):
    session = clean_db
    creator = Creator(name="Pending Creator", discovery_source="test")
    niche = Niche(canonical_name="pending-niche", depth=0)
    session.add_all([creator, niche])
    await session.flush()

    cluster = ProblemCluster(
        creator_id=creator.id, label="X", frequency=1, evidence_strength=0.5
    )
    session.add(cluster)
    await session.flush()

    opp = OpportunityScore(
        creator_id=creator.id,
        problem_cluster_id=cluster.id,
        component_scores={},
        aggregate_score=0.5,
        computed_hash="hash-pending",
        confidence_band=ConfidenceBand.LOW,
        rule_version="v1",
        model_version="fixture",
    )
    session.add(opp)
    await session.flush()

    dossier = Dossier(
        creator_id=creator.id,
        niche_id=niche.id,
        opportunity_score_id=opp.id,
        content={},
        status=DossierStatus.PENDING_REVIEW,
    )
    session.add(dossier)
    await session.commit()

    async with _make_client(session) as client:
        resp = await client.get(f"/dossiers/{dossier.id}/handoff")

    assert resp.status_code == 403
    assert "approved" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_handoff_returns_404_for_unknown_dossier(clean_db: AsyncSession):
    session = clean_db

    async with _make_client(session) as client:
        resp = await client.get("/dossiers/nonexistent-id/handoff")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()
