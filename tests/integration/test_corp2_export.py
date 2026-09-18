"""Integration tests for the CORP1 -> CORP2 handoff package (CORP1 Stage
5, T9) against real Postgres.

The frozen acceptance criterion requires the package be "fully
reconstructable from Dossier + dossier_evidence + Niche.parent_niche_id
walk alone, with no other CORP1 table access required" (plus one direct
HumanDecision lookup for the reviewer's own decision-gate notes -- see
corp2_export.py's module docstring for why that lookup is necessary and
in scope). These tests seed the minimum required by FK constraints
(OpportunityScore/ProblemCluster, since Dossier.opportunity_score_id is
NOT NULL) but never assert anything through them -- proving the package
itself doesn't depend on their content -- and a static check confirms
build_handoff_package's own source never references those model names
at all.
"""

import ast
import inspect
import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import corp.workers.handoff.corp2_export as corp2_export
from corp.core.models.creator import Creator
from corp.core.models.dossier import Dossier, DossierEvidence, DossierStatus
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.intelligence import ProblemCluster
from corp.core.models.niche import Niche
from corp.core.models.scoring import ConfidenceBand, OpportunityScore
from corp.core.models.workflow import DecisionType, Gate, HumanDecision
from corp.workers.handoff.corp2_export import build_handoff_package

# ---------- Seed helpers ----------


async def _make_creator(session: AsyncSession) -> Creator:
    creator = Creator(name="Handoff Creator", discovery_source="test")
    session.add(creator)
    await session.flush()
    return creator


async def _make_niche(
    session: AsyncSession, name: str, parent_niche_id: str | None = None, depth: int = 0
) -> Niche:
    niche = Niche(canonical_name=name, parent_niche_id=parent_niche_id, depth=depth)
    session.add(niche)
    await session.flush()
    return niche


async def _make_evidence(session: AsyncSession, text: str, external_id: str) -> Evidence:
    evidence = Evidence(
        source_type="comment",
        source_id=external_id,
        source_platform="youtube",
        raw_text=text,
        source_url="https://example.com/" + external_id,
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
    )
    session.add(evidence)
    await session.flush()
    return evidence


async def _make_dossier(
    session: AsyncSession,
    creator: Creator,
    niche: Niche,
    *,
    status: DossierStatus = DossierStatus.APPROVED,
    content: dict[str, Any] | None = None,
) -> Dossier:
    # Only exists to satisfy Dossier.opportunity_score_id's NOT NULL FK --
    # build_handoff_package never queries either of these tables (see the
    # static check below).
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
        computed_hash="hash-t9",
        confidence_band=ConfidenceBand.HIGH,
        rule_version="v1.0.0",
        model_version="fixture",
    )
    session.add(opp)
    await session.flush()

    dossier = Dossier(
        creator_id=creator.id,
        niche_id=niche.id,
        opportunity_score_id=opp.id,
        content=content or {"score_band": "Strong opportunity", "product_ideas": []},
        status=status,
    )
    session.add(dossier)
    await session.flush()
    return dossier


async def _link_evidence(session: AsyncSession, dossier: Dossier, evidence: Evidence) -> None:
    session.add(DossierEvidence(dossier_id=dossier.id, evidence_id=evidence.id))
    await session.flush()


async def _approve(
    session: AsyncSession, dossier: Dossier, *, rationale: str, decided_by: str = "reviewer-1"
) -> HumanDecision:
    decision = HumanDecision(
        creator_id=dossier.creator_id,
        dossier_id=dossier.id,
        decision=DecisionType.APPROVE,
        gate=Gate.GATE_D,
        rationale=rationale,
        decided_by=decided_by,
    )
    session.add(decision)
    await session.flush()
    return decision


# ---------- Happy path ----------


@pytest.mark.asyncio
async def test_package_contains_full_dossier_and_evidence_trail(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    dossier = await _make_dossier(session, creator, niche)
    e1 = await _make_evidence(session, "grinder review one", "ev1")
    e2 = await _make_evidence(session, "grinder review two", "ev2")
    await _link_evidence(session, dossier, e1)
    await _link_evidence(session, dossier, e2)
    await _approve(session, dossier, rationale="Strong evidence, approving.")
    await session.commit()

    package = await build_handoff_package(session, dossier.id)

    assert package.dossier_id == dossier.id
    assert package.creator_id == creator.id
    assert package.niche_id == niche.id
    assert package.dossier_status == "approved"
    assert package.dossier_content == dossier.content
    assert {e.id for e in package.evidence_trail} == {e1.id, e2.id}
    texts = {e.raw_text for e in package.evidence_trail}
    assert texts == {"grinder review one", "grinder review two"}


@pytest.mark.asyncio
async def test_package_with_zero_linked_evidence_has_empty_trail(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    dossier = await _make_dossier(session, creator, niche)
    await _approve(session, dossier, rationale="Approved with no linked evidence.")
    await session.commit()

    package = await build_handoff_package(session, dossier.id)

    assert package.evidence_trail == []


@pytest.mark.asyncio
async def test_package_includes_reviewer_decision_notes(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    dossier = await _make_dossier(session, creator, niche)
    await _approve(
        session, dossier, rationale="Clear demand signal.", decided_by="alice@example.com"
    )
    await session.commit()

    package = await build_handoff_package(session, dossier.id)

    assert package.decision_notes == "Clear demand signal."
    assert package.decided_by == "alice@example.com"
    assert package.decided_at is not None


@pytest.mark.asyncio
async def test_decision_notes_none_when_no_approve_decision_recorded(clean_db: AsyncSession):
    """Robustness: a Dossier row can be forced to APPROVED with no
    HumanDecision row behind it (e.g. a data-migration edge case) -- the
    package must not crash, just have no notes."""
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    dossier = await _make_dossier(session, creator, niche)
    await session.commit()

    package = await build_handoff_package(session, dossier.id)

    assert package.decision_notes is None
    assert package.decided_at is None
    assert package.decided_by is None


@pytest.mark.asyncio
async def test_niche_path_walks_parent_chain_root_to_leaf(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    root = await _make_niche(session, "Automotive", depth=0)
    child = await _make_niche(session, "Track Builds", parent_niche_id=root.id, depth=1)
    leaf = await _make_niche(session, "Suspension", parent_niche_id=child.id, depth=2)
    dossier = await _make_dossier(session, creator, leaf)
    await _approve(session, dossier, rationale="Approved")
    await session.commit()

    package = await build_handoff_package(session, dossier.id)

    assert [n.canonical_name for n in package.niche_path] == [
        "Automotive",
        "Track Builds",
        "Suspension",
    ]
    assert [n.depth for n in package.niche_path] == [0, 1, 2]


# ---------- Edge cases ----------


@pytest.mark.asyncio
async def test_dossier_not_found_raises(clean_db: AsyncSession):
    with pytest.raises(ValueError, match="Dossier not found"):
        await build_handoff_package(clean_db, "does-not-exist")


@pytest.mark.asyncio
async def test_unapproved_dossier_raises(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    dossier = await _make_dossier(session, creator, niche, status=DossierStatus.PENDING_REVIEW)
    await session.commit()

    with pytest.raises(ValueError, match="not approved"):
        await build_handoff_package(session, dossier.id)


# ---------- Serialization ----------


@pytest.mark.asyncio
async def test_to_dict_is_json_serializable(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    root = await _make_niche(session, "Automotive", depth=0)
    leaf = await _make_niche(session, "Track Builds", parent_niche_id=root.id, depth=1)
    dossier = await _make_dossier(session, creator, leaf)
    ev = await _make_evidence(session, "some evidence", "ev1")
    await _link_evidence(session, dossier, ev)
    await _approve(session, dossier, rationale="Approved for handoff.")
    await session.commit()

    package = await build_handoff_package(session, dossier.id)
    payload = package.to_dict()
    raw = json.dumps(payload)  # must not raise
    parsed = json.loads(raw)

    assert parsed["dossier_id"] == dossier.id
    assert isinstance(parsed["generated_at"], str)
    assert isinstance(parsed["evidence_trail"][0]["collected_at"], str)
    assert isinstance(parsed["decided_at"], str)


# ---------- Scope proof: no access beyond the five named tables ----------


def test_module_never_imports_upstream_pipeline_tables():
    """Static proof matching the acceptance criterion's own wording:
    reconstruction needs Dossier + dossier_evidence + Evidence (the
    evidence trail) + Niche (the parent_niche_id walk) + one direct
    HumanDecision lookup -- nothing from the heavier upstream pipeline
    (ProblemCluster, OpportunityScore, CreatorScore, NicheCandidate) that
    Dossier.content was originally rendered from. Checks actual imported
    names (an AST walk), not a raw substring match against the source --
    the module's own docstring legitimately names these tables to explain
    why they're unnecessary.

    Known limitation (Stage 8 review): this only catches a direct
    `from ... import Name` / `import module` of a forbidden symbol. It
    would not catch `import corp.core.models.intelligence as m` followed
    by `m.ProblemCluster`, or a dynamic `importlib.import_module(...)`.
    Neither pattern appears in this module today; flagged here rather
    than silently trusted."""
    tree = ast.parse(inspect.getsource(corp2_export))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    forbidden = {"ProblemCluster", "OpportunityScore", "CreatorScore", "NicheCandidate"}
    assert not (imported_names & forbidden), imported_names & forbidden
