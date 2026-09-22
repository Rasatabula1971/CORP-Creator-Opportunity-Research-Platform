"""Integration tests for CORP1 Stage 4 / T0: the niche + niche-candidate
drill-down tree, Evidence.evidence_type, the RESEARCH_MORE decision, and the
new Dossier / DossierEvidence models — against real Postgres."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
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
from corp.core.models.niche_candidate import NicheCandidate, NicheCandidateStatus
from corp.core.models.scoring import ConfidenceBand, OpportunityScore
from corp.core.models.workflow import DecisionType, Gate, HumanDecision, ResearchRun, RunType

# ---------- Niche drill-down tree ----------


@pytest.mark.asyncio
async def test_niche_defaults_to_depth_zero_and_no_parent(clean_db: AsyncSession):
    session = clean_db
    niche = Niche(canonical_name="Automotive")
    session.add(niche)
    await session.flush()
    assert niche.depth == 0
    assert niche.parent_niche_id is None


@pytest.mark.asyncio
async def test_niche_drill_down_tree_traversal(clean_db: AsyncSession):
    session = clean_db
    root = Niche(canonical_name="Automotive", depth=0)
    session.add(root)
    await session.flush()

    child = Niche(canonical_name="Track Builds", parent_niche_id=root.id, depth=1)
    session.add(child)
    await session.flush()

    grandchild = Niche(canonical_name="Suspension", parent_niche_id=child.id, depth=2)
    session.add(grandchild)
    await session.flush()

    await session.refresh(root, ["child_niches"])
    assert len(root.child_niches) == 1
    assert root.child_niches[0].canonical_name == "Track Builds"

    await session.refresh(grandchild, ["parent_niche"])
    assert grandchild.parent_niche is not None
    assert grandchild.parent_niche.id == child.id
    assert grandchild.depth == 2


# ---------- NicheCandidate drill-down tree + DRILLING status ----------


async def _create_candidate(
    session: AsyncSession, *, depth: int = 0, parent_candidate_id: str | None = None
) -> NicheCandidate:
    campaign = Campaign(name="Drill Test")
    session.add(campaign)
    await session.flush()

    run = ResearchRun(run_type=RunType.NICHE_DISCOVERY.value, campaign_id=campaign.id, status="running")
    session.add(run)
    await session.flush()

    candidate = NicheCandidate(
        campaign_id=campaign.id,
        research_run_id=run.id,
        label="Track Builds",
        naming_method="llm",
        evidence_count=1,
        source_count=1,
        author_count=1,
        depth=depth,
        parent_candidate_id=parent_candidate_id,
    )
    session.add(candidate)
    await session.flush()
    return candidate


@pytest.mark.asyncio
async def test_niche_candidate_defaults_to_depth_zero(clean_db: AsyncSession):
    candidate = await _create_candidate(clean_db)
    assert candidate.depth == 0
    assert candidate.parent_candidate_id is None


@pytest.mark.asyncio
async def test_niche_candidate_drill_down_tree_traversal(clean_db: AsyncSession):
    session = clean_db
    parent = await _create_candidate(session, depth=1)
    child = await _create_candidate(session, depth=2, parent_candidate_id=parent.id)

    await session.refresh(parent, ["child_candidates"])
    assert len(parent.child_candidates) == 1
    assert parent.child_candidates[0].id == child.id


@pytest.mark.asyncio
async def test_niche_candidate_drilling_status_persists(clean_db: AsyncSession):
    session = clean_db
    candidate = await _create_candidate(session)
    candidate.status = NicheCandidateStatus.DRILLING
    await session.flush()

    result = await session.execute(select(NicheCandidate).where(NicheCandidate.id == candidate.id))
    reloaded = result.scalar_one()
    assert reloaded.status == NicheCandidateStatus.DRILLING


# ---------- Evidence.evidence_type ----------


@pytest.mark.asyncio
async def test_evidence_type_persists(clean_db: AsyncSession):
    session = clean_db
    evidence = Evidence(
        source_type="trend_point",
        source_id="trend_001",
        source_platform="google_trends",
        raw_text="small business invoicing: rising interest",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        evidence_type=EvidenceType.TREND,
        origin=EvidenceOrigin.OBSERVATION,
    )
    session.add(evidence)
    await session.flush()

    result = await session.execute(select(Evidence).where(Evidence.id == evidence.id))
    reloaded = result.scalar_one()
    assert reloaded.evidence_type == EvidenceType.TREND


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["evidence_type", "origin"])
async def test_evidence_provenance_fields_are_required(clean_db: AsyncSession, missing: str):
    """Provenance Invariant, database half (R3): a row without evidence_type or
    origin is rejected at the schema level, not just by the code paths."""
    session = clean_db
    kwargs: dict[str, object] = {
        "source_type": "comment",
        "source_id": "cmt_missing_provenance",
        "source_platform": "youtube",
        "raw_text": "row attempting to skip provenance",
        "access_method": AccessMethod.OFFICIAL,
        "compliance_status": ComplianceStatus.COMPLIANT,
        "origin": EvidenceOrigin.OBSERVATION,
        "evidence_type": EvidenceType.PROBLEM,
    }
    kwargs[missing] = None
    session.add(Evidence(**kwargs))
    with pytest.raises(IntegrityError):
        await session.flush()


# ---------- Dossier + DossierEvidence ----------


async def _create_dossier_prereqs(session: AsyncSession) -> tuple[Creator, Niche, OpportunityScore]:
    creator = Creator(name="Creator A", niche="automotive", discovery_source="manual")
    session.add(creator)
    niche = Niche(canonical_name="Track Builds")
    session.add(niche)
    await session.flush()

    cluster = ProblemCluster(creator_id=creator.id, label="Suspension setup confusion", frequency=3, evidence_strength=0.7)
    session.add(cluster)
    await session.flush()

    score = OpportunityScore(
        creator_id=creator.id,
        problem_cluster_id=cluster.id,
        component_scores={"frequency": 0.7},
        aggregate_score=0.7,
        computed_hash="abc123",
        confidence_band=ConfidenceBand.MEDIUM,
        rule_version="v1.0.0",
        model_version="gemini-1.5-flash",
    )
    session.add(score)
    await session.flush()
    return creator, niche, score


@pytest.mark.asyncio
async def test_dossier_defaults_to_pending_review(clean_db: AsyncSession):
    session = clean_db
    creator, niche, score = await _create_dossier_prereqs(session)

    dossier = Dossier(
        creator_id=creator.id,
        niche_id=niche.id,
        opportunity_score_id=score.id,
        content={"recommendation": "Approve for outreach"},
    )
    session.add(dossier)
    await session.flush()

    assert dossier.status == DossierStatus.PENDING_REVIEW
    assert dossier.generated_at is not None
    assert dossier.superseded_at is None


@pytest.mark.asyncio
async def test_dossier_evidence_trail(clean_db: AsyncSession):
    session = clean_db
    creator, niche, score = await _create_dossier_prereqs(session)
    dossier = Dossier(
        creator_id=creator.id,
        niche_id=niche.id,
        opportunity_score_id=score.id,
        content={},
    )
    session.add(dossier)
    await session.flush()

    evidence = Evidence(
        source_type="trend_point",
        source_id="trend_002",
        source_platform="google_trends",
        raw_text="suspension setup guide demand",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        evidence_type=EvidenceType.TREND,
        origin=EvidenceOrigin.OBSERVATION,
    )
    session.add(evidence)
    await session.flush()

    link = DossierEvidence(dossier_id=dossier.id, evidence_id=evidence.id)
    session.add(link)
    await session.flush()

    await session.refresh(dossier, ["evidence"])
    assert len(dossier.evidence) == 1
    assert dossier.evidence[0].evidence_id == evidence.id


@pytest.mark.asyncio
async def test_dossier_evidence_duplicate_pair_rejected(clean_db: AsyncSession):
    session = clean_db
    creator, niche, score = await _create_dossier_prereqs(session)
    dossier = Dossier(
        creator_id=creator.id, niche_id=niche.id, opportunity_score_id=score.id, content={}
    )
    evidence = Evidence(
        source_type="trend_point",
        source_id="trend_003",
        source_platform="google_trends",
        raw_text="duplicate link test",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        origin=EvidenceOrigin.OBSERVATION,
        evidence_type=EvidenceType.TREND,
    )
    session.add_all([dossier, evidence])
    await session.flush()

    session.add(DossierEvidence(dossier_id=dossier.id, evidence_id=evidence.id))
    await session.flush()

    session.add(DossierEvidence(dossier_id=dossier.id, evidence_id=evidence.id))
    with pytest.raises(IntegrityError):
        await session.flush()


# ---------- HumanDecision: RESEARCH_MORE + dossier_id ----------


@pytest.mark.asyncio
async def test_human_decision_research_more_against_dossier(clean_db: AsyncSession):
    session = clean_db
    creator, niche, score = await _create_dossier_prereqs(session)
    dossier = Dossier(
        creator_id=creator.id, niche_id=niche.id, opportunity_score_id=score.id, content={}
    )
    session.add(dossier)
    await session.flush()

    decision = HumanDecision(
        creator_id=creator.id,
        dossier_id=dossier.id,
        decision=DecisionType.RESEARCH_MORE,
        gate=Gate.GATE_A,
        rationale="Promising but need more evidence",
    )
    session.add(decision)
    await session.flush()

    result = await session.execute(select(HumanDecision).where(HumanDecision.id == decision.id))
    reloaded = result.scalar_one()
    assert reloaded.decision == DecisionType.RESEARCH_MORE
    assert reloaded.dossier_id == dossier.id


@pytest.mark.asyncio
async def test_human_decision_dossier_id_optional_for_backward_compatibility(
    clean_db: AsyncSession,
):
    """Pre-Dossier decisions (creator-only) must keep working unmodified."""
    session = clean_db
    creator = Creator(name="Legacy Creator", niche="tech", discovery_source="manual")
    session.add(creator)
    await session.flush()

    decision = HumanDecision(
        creator_id=creator.id,
        decision=DecisionType.APPROVE,
        gate=Gate.GATE_A,
    )
    session.add(decision)
    await session.flush()
    assert decision.dossier_id is None


# ---------- Every new enum value is reachable from the ORM (T0 acceptance) ----------


@pytest.mark.parametrize("evidence_type", list(EvidenceType))
@pytest.mark.asyncio
async def test_every_evidence_type_round_trips(clean_db: AsyncSession, evidence_type: EvidenceType):
    session = clean_db
    evidence = Evidence(
        source_type="fixture",
        source_id=f"fixture_{evidence_type.value}",
        source_platform="fixture",
        raw_text="enum coverage fixture",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        evidence_type=evidence_type,
        origin=EvidenceOrigin.OBSERVATION,
    )
    session.add(evidence)
    await session.flush()

    result = await session.execute(select(Evidence).where(Evidence.id == evidence.id))
    assert result.scalar_one().evidence_type == evidence_type


@pytest.mark.parametrize("status", list(DossierStatus))
@pytest.mark.asyncio
async def test_every_dossier_status_round_trips(clean_db: AsyncSession, status: DossierStatus):
    session = clean_db
    creator, niche, score = await _create_dossier_prereqs(session)

    dossier = Dossier(
        creator_id=creator.id,
        niche_id=niche.id,
        opportunity_score_id=score.id,
        content={},
        status=status,
    )
    session.add(dossier)
    await session.flush()

    result = await session.execute(select(Dossier).where(Dossier.id == dossier.id))
    assert result.scalar_one().status == status


@pytest.mark.parametrize("candidate_status", list(NicheCandidateStatus))
@pytest.mark.asyncio
async def test_every_niche_candidate_status_round_trips(
    clean_db: AsyncSession, candidate_status: NicheCandidateStatus
):
    session = clean_db
    candidate = await _create_candidate(session)
    candidate.status = candidate_status
    await session.flush()

    result = await session.execute(select(NicheCandidate).where(NicheCandidate.id == candidate.id))
    assert result.scalar_one().status == candidate_status


@pytest.mark.parametrize("decision_type", list(DecisionType))
@pytest.mark.asyncio
async def test_every_decision_type_round_trips(clean_db: AsyncSession, decision_type: DecisionType):
    session = clean_db
    creator = Creator(name=f"Creator {decision_type.value}", niche="tech", discovery_source="manual")
    session.add(creator)
    await session.flush()

    decision = HumanDecision(creator_id=creator.id, decision=decision_type, gate=Gate.GATE_A)
    session.add(decision)
    await session.flush()

    result = await session.execute(select(HumanDecision).where(HumanDecision.id == decision.id))
    assert result.scalar_one().decision == decision_type
