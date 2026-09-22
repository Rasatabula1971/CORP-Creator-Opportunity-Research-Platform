"""Integration tests for the registry re-scan scheduler (CORP1 Stage 5,
T10) against real Postgres.

The frozen test requirement is a time-travel test: a watched dossier
past its niche's recheck date gets re-scored, a fresh one does not.
"Mocked clock" here means dependency-injecting ``now`` into
rescan_watched_dossiers()/find_due_watched_dossiers() rather than
monkeypatching datetime.now() globally -- deterministic, and it can't
bleed into any other test running in the same process.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator
from corp.core.models.dossier import Dossier, DossierStatus
from corp.core.models.evidence import (
    AccessMethod,
    ComplianceStatus,
    Evidence,
    EvidenceOrigin,
    EvidenceType,
)
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.niche import Niche
from corp.core.models.scoring import ConfidenceBand, CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.runs import supersede
from corp.workers.scheduler.registry_rescan import (
    find_due_watched_dossiers,
    rescan_watched_dossiers,
)

RULES_PATH = "rules/scoring.yaml"
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

# ---------- Seed helpers (mirrors tests/integration/test_dossier_persistence.py) ----------


async def _make_creator(session: AsyncSession, name: str = "Rescan Creator") -> Creator:
    creator = Creator(name=name, niche="home espresso", discovery_source="manual")
    session.add(creator)
    await session.flush()
    return creator


async def _make_niche(
    session: AsyncSession, name: str, *, next_recheck_at: datetime | None
) -> Niche:
    niche = Niche(
        canonical_name=name,
        last_researched_at=NOW - timedelta(days=91) if next_recheck_at else None,
        next_recheck_at=next_recheck_at,
    )
    session.add(niche)
    await session.flush()
    return niche


async def _make_run(session: AsyncSession, creator_id: str) -> ResearchRun:
    run = ResearchRun(creator_id=creator_id, status="completed")
    session.add(run)
    await session.flush()
    return run


async def _make_evidence(session: AsyncSession, run_id: str, text: str) -> Evidence:
    evidence = Evidence(
        source_type="comment",
        source_id=f"cmt_{text[:20]}",
        source_platform="youtube",
        raw_text=text,
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        research_run_id=run_id,
        origin=EvidenceOrigin.OBSERVATION,
        evidence_type=EvidenceType.PROBLEM,
    )
    session.add(evidence)
    await session.flush()
    return evidence


async def _make_scored_opportunity(
    session: AsyncSession, creator: Creator, run: ResearchRun
) -> OpportunityScore:
    cluster = ProblemCluster(
        creator_id=creator.id, label="Grinder confusion", frequency=3, evidence_strength=0.8
    )
    session.add(cluster)
    await session.flush()

    evidence = await _make_evidence(session, run.id, "I wish there was a grinder chart")
    obs = ProblemObservation(
        evidence_id=evidence.id,
        text=evidence.raw_text,
        is_inferred=False,
        extraction_prompt_version="v1.0",
        model_version="fixture",
    )
    session.add(obs)
    await session.flush()
    session.add(
        ProblemClusterMember(cluster_id=cluster.id, observation_id=obs.id, similarity_score=0.9)
    )
    await session.flush()

    session.add(
        CreatorScore(
            creator_id=creator.id,
            component_scores={"frequency": 0.75},
            aggregate_score=0.75,
            computed_hash="hash1",
            confidence_band=ConfidenceBand.HIGH,
            rule_version="v1.0.0",
            model_version="fixture",
        )
    )
    opp = OpportunityScore(
        creator_id=creator.id,
        problem_cluster_id=cluster.id,
        component_scores={"frequency": 0.75},
        aggregate_score=0.75,
        computed_hash="hash2",
        confidence_band=ConfidenceBand.HIGH,
        rule_version="v1.0.0",
        model_version="fixture",
        research_run_id=run.id,
    )
    session.add(opp)
    await session.commit()
    return opp


async def _make_watching_dossier(
    session: AsyncSession, creator: Creator, niche: Niche, opp: OpportunityScore
) -> Dossier:
    dossier = Dossier(
        creator_id=creator.id,
        niche_id=niche.id,
        opportunity_score_id=opp.id,
        content={"score_band": "Moderate — worth watching"},
        status=DossierStatus.WATCHING,
    )
    session.add(dossier)
    await session.commit()
    return dossier


# ---------- find_due_watched_dossiers ----------


@pytest.mark.asyncio
async def test_finds_watched_dossier_past_recheck_date(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso", next_recheck_at=NOW - timedelta(days=1))
    run = await _make_run(session, creator.id)
    opp = await _make_scored_opportunity(session, creator, run)
    dossier = await _make_watching_dossier(session, creator, niche, opp)

    due = await find_due_watched_dossiers(session, now=NOW)

    assert [d.id for d in due] == [dossier.id]


@pytest.mark.asyncio
async def test_ignores_watched_dossier_with_fresh_niche(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso", next_recheck_at=NOW + timedelta(days=10))
    run = await _make_run(session, creator.id)
    opp = await _make_scored_opportunity(session, creator, run)
    await _make_watching_dossier(session, creator, niche, opp)

    due = await find_due_watched_dossiers(session, now=NOW)

    assert due == []


@pytest.mark.asyncio
async def test_ignores_non_watching_dossier_even_if_niche_due(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso", next_recheck_at=NOW - timedelta(days=1))
    run = await _make_run(session, creator.id)
    opp = await _make_scored_opportunity(session, creator, run)
    dossier = Dossier(
        creator_id=creator.id,
        niche_id=niche.id,
        opportunity_score_id=opp.id,
        content={},
        status=DossierStatus.PENDING_REVIEW,
    )
    session.add(dossier)
    await session.commit()

    due = await find_due_watched_dossiers(session, now=NOW)

    assert due == []


@pytest.mark.asyncio
async def test_ignores_already_superseded_watching_dossier(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso", next_recheck_at=NOW - timedelta(days=1))
    run = await _make_run(session, creator.id)
    opp = await _make_scored_opportunity(session, creator, run)
    dossier = await _make_watching_dossier(session, creator, niche, opp)
    dossier.superseded_at = NOW - timedelta(hours=1)
    await session.commit()

    due = await find_due_watched_dossiers(session, now=NOW)

    assert due == []


# ---------- rescan_watched_dossiers (the frozen time-travel test) ----------


@pytest.mark.asyncio
async def test_watched_dossier_past_recheck_date_gets_rescored(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso", next_recheck_at=NOW - timedelta(days=1))
    run = await _make_run(session, creator.id)
    opp = await _make_scored_opportunity(session, creator, run)
    old_dossier = await _make_watching_dossier(session, creator, niche, opp)

    stats = await rescan_watched_dossiers(session, RULES_PATH, now=NOW)
    await session.commit()

    assert stats.checked == 1
    assert stats.rescored == 1
    assert stats.failed == 0

    await session.refresh(old_dossier)
    assert old_dossier.superseded_at is not None  # superseded, latest-wins (T6 convention)

    rows = (
        await session.execute(
            select(Dossier).where(Dossier.creator_id == creator.id).order_by(Dossier.generated_at)
        )
    ).scalars().all()
    assert len(rows) == 2  # never deleted -- both the old and the new row exist
    new_dossier = rows[-1]
    assert new_dossier.id != old_dossier.id
    assert new_dossier.superseded_at is None
    assert new_dossier.status == DossierStatus.PENDING_REVIEW  # T6's generator default


@pytest.mark.asyncio
async def test_fresh_watched_dossier_not_rescored(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso", next_recheck_at=NOW + timedelta(days=10))
    run = await _make_run(session, creator.id)
    opp = await _make_scored_opportunity(session, creator, run)
    dossier = await _make_watching_dossier(session, creator, niche, opp)

    stats = await rescan_watched_dossiers(session, RULES_PATH, now=NOW)
    await session.commit()

    assert stats.checked == 0
    assert stats.rescored == 0

    await session.refresh(dossier)
    assert dossier.superseded_at is None
    assert dossier.status == DossierStatus.WATCHING

    rows = (
        await session.execute(select(Dossier).where(Dossier.creator_id == creator.id))
    ).scalars().all()
    assert len(rows) == 1  # no new dossier created


@pytest.mark.asyncio
async def test_niche_next_recheck_at_advanced_after_rescore(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso", next_recheck_at=NOW - timedelta(days=1))
    run = await _make_run(session, creator.id)
    opp = await _make_scored_opportunity(session, creator, run)
    await _make_watching_dossier(session, creator, niche, opp)

    await rescan_watched_dossiers(session, RULES_PATH, now=NOW, recheck_days=90)
    await session.commit()

    await session.refresh(niche)
    assert niche.last_researched_at == NOW
    assert niche.next_recheck_at == NOW + timedelta(days=90)


@pytest.mark.asyncio
async def test_one_failing_dossier_does_not_block_the_batch(clean_db: AsyncSession):
    session = clean_db

    # Dossier A: its OpportunityScore gets superseded before the rescan,
    # so DossierGenerator.generate_and_persist raises "no active
    # opportunity scores" -- must be logged and skipped, not fatal.
    creator_a = await _make_creator(session, "Creator A")
    niche_a = await _make_niche(
        session, "Home Espresso A", next_recheck_at=NOW - timedelta(days=1)
    )
    run_a = await _make_run(session, creator_a.id)
    opp_a = await _make_scored_opportunity(session, creator_a, run_a)
    await _make_watching_dossier(session, creator_a, niche_a, opp_a)
    await supersede(session, OpportunityScore, OpportunityScore.creator_id == creator_a.id)
    await session.commit()

    # Dossier B: healthy, must still succeed in the same batch.
    creator_b = await _make_creator(session, "Creator B")
    niche_b = await _make_niche(
        session, "Home Espresso B", next_recheck_at=NOW - timedelta(days=1)
    )
    run_b = await _make_run(session, creator_b.id)
    opp_b = await _make_scored_opportunity(session, creator_b, run_b)
    await _make_watching_dossier(session, creator_b, niche_b, opp_b)

    stats = await rescan_watched_dossiers(session, RULES_PATH, now=NOW)
    await session.commit()

    assert stats.checked == 2
    assert stats.rescored == 1
    assert stats.failed == 1

    b_rows = (
        await session.execute(select(Dossier).where(Dossier.creator_id == creator_b.id))
    ).scalars().all()
    assert len(b_rows) == 2  # creator B's dossier was regenerated despite A's failure
