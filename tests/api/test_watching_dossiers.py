"""GET /dossiers/watching — R12d: each watched dossier carries its last
re-research outcome (design §3.5), from either trigger: ``unchanged`` or
``resurfaced`` from the dossier's own ``rescan`` block, ``failed`` from the
newest failed ``watch_rescan`` run that targeted it, whichever is newer;
nothing when never re-researched."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.dossier import Dossier, DossierStatus
from corp.core.models.intelligence import ProblemCluster
from corp.core.models.niche import Niche
from corp.core.models.scoring import ConfidenceBand, OpportunityScore
from corp.core.models.workflow import ResearchRun, RunType
from tests.api.test_dossier_decision_endpoint import _make_client

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


async def _watching(session: AsyncSession, content: dict[str, object] | None = None) -> Dossier:
    tag = uuid.uuid4().hex[:8]
    creator = Creator(name=f"Watched {tag}", discovery_source="test", status=CreatorStatus.WATCHING)
    niche = Niche(canonical_name=f"Niche {tag}", depth=0)
    session.add_all([creator, niche])
    await session.flush()
    cluster = ProblemCluster(
        creator_id=creator.id, label="Grinder confusion", frequency=3, evidence_strength=0.8
    )
    session.add(cluster)
    await session.flush()
    opp = OpportunityScore(
        creator_id=creator.id, problem_cluster_id=cluster.id, component_scores={"frequency": 0.7},
        aggregate_score=0.7, computed_hash=f"hash-{tag}", confidence_band=ConfidenceBand.HIGH,
        rule_version="v1.0.0", model_version="fixture",
    )
    session.add(opp)
    await session.flush()
    dossier = Dossier(
        creator_id=creator.id, niche_id=niche.id, opportunity_score_id=opp.id,
        status=DossierStatus.WATCHING, content=content or {"score_band": "Moderate"},
    )
    session.add(dossier)
    await session.commit()
    return dossier


async def _failed_rescan(
    session: AsyncSession, dossier: Dossier, *, at: datetime, error: str
) -> ResearchRun:
    run = ResearchRun(
        creator_id=dossier.creator_id,
        status="failed",
        run_type=RunType.WATCH_RESCAN.value,
        config_snapshot={"trigger": "watch", "dossier_id": dossier.id},
        started_at=at - timedelta(minutes=5),
        completed_at=at,
        error_message=error,
    )
    session.add(run)
    await session.commit()
    return run


@pytest.mark.asyncio
async def test_never_rescanned_has_no_last_rescan(clean_db: AsyncSession):
    session = clean_db
    dossier = await _watching(session)

    async with _make_client(session) as client:
        resp = await client.get("/dossiers/watching")

    assert resp.status_code == 200
    [row] = resp.json()
    assert row["id"] == dossier.id and row["last_rescan"] is None


@pytest.mark.asyncio
async def test_unchanged_outcome_comes_from_the_rescan_block(clean_db: AsyncSession):
    session = clean_db
    await _watching(session, {
        "score_band": "x",
        "rescan": {
            "trigger": "watch", "previous_dossier_id": "prev", "resurfaced": False,
            "reason": "unchanged: score +0.010, 2 new evidence rows",
            "score_delta": 0.01, "new_evidence_count": 2, "run_id": "run-1",
            "at": T0.isoformat(),
        },
    })

    async with _make_client(session) as client:
        [row] = (await client.get("/dossiers/watching")).json()

    assert row["last_rescan"] == {
        "outcome": "unchanged",
        "trigger": "watch",
        "at": "2026-09-01T12:00:00Z",
        "reason": "unchanged: score +0.010, 2 new evidence rows",
        "score_delta": 0.01,
        "new_evidence_count": 2,
        "error": None,
        "run_id": "run-1",
    }


@pytest.mark.asyncio
async def test_failed_outcome_comes_from_the_newest_failed_run(clean_db: AsyncSession):
    session = clean_db
    dossier = await _watching(session)
    await _failed_rescan(session, dossier, at=T0, error="creator_research: old")
    newest = await _failed_rescan(
        session, dossier, at=T0 + timedelta(days=1), error="research_more: quota"
    )
    other = await _watching(session)  # a failed run for another dossier is not ours

    async with _make_client(session) as client:
        rows = {r["id"]: r for r in (await client.get("/dossiers/watching")).json()}

    assert rows[other.id]["last_rescan"] is None
    last = rows[dossier.id]["last_rescan"]
    assert last["outcome"] == "failed"
    assert last["error"] == "research_more: quota" and last["run_id"] == newest.id
    assert last["at"] == "2026-09-02T12:00:00Z"


@pytest.mark.asyncio
async def test_newer_outcome_wins(clean_db: AsyncSession):
    """An unchanged re-scan followed by a failed one reports the failure;
    the reverse reports unchanged."""
    session = clean_db
    block = {
        "trigger": "watch", "previous_dossier_id": "p", "resurfaced": False,
        "reason": "unchanged", "score_delta": 0.0, "new_evidence_count": 0,
        "run_id": "r", "at": T0.isoformat(),
    }
    then_failed = await _watching(session, {"rescan": block})
    await _failed_rescan(session, then_failed, at=T0 + timedelta(days=1), error="later")
    later = (T0 + timedelta(days=2)).isoformat()
    failed_first = await _watching(session, {"rescan": {**block, "at": later}})
    await _failed_rescan(session, failed_first, at=T0, error="earlier")

    async with _make_client(session) as client:
        rows = {r["id"]: r for r in (await client.get("/dossiers/watching")).json()}

    assert rows[then_failed.id]["last_rescan"]["outcome"] == "failed"
    assert rows[failed_first.id]["last_rescan"]["outcome"] == "unchanged"


@pytest.mark.asyncio
async def test_resurfaced_then_rewatched_reports_resurfaced(clean_db: AsyncSession):
    """Stage 8: a re-scan resurfaced the dossier, the reviewer parked it
    again -- the block still says resurfaced, so must the page. A Research
    More result parked afterwards names its trigger."""
    session = clean_db
    rewatched = await _watching(session, {"rescan": {
        "trigger": "watch", "previous_dossier_id": "p", "resurfaced": True,
        "reason": "score +0.080; confidence medium → high", "score_delta": 0.08,
        "new_evidence_count": 14, "run_id": "r", "at": T0.isoformat(),
    }})
    after_research_more = await _watching(session, {"rescan": {
        "trigger": "research_more", "previous_dossier_id": "p", "resurfaced": True,
        "reason": "research more requested by reviewer", "score_delta": None,
        "new_evidence_count": 0, "run_id": "r2", "at": T0.isoformat(),
    }})

    async with _make_client(session) as client:
        rows = {r["id"]: r for r in (await client.get("/dossiers/watching")).json()}

    assert rows[rewatched.id]["last_rescan"]["outcome"] == "resurfaced"
    assert rows[rewatched.id]["last_rescan"]["trigger"] == "watch"
    last = rows[after_research_more.id]["last_rescan"]
    assert (last["outcome"], last["trigger"], last["score_delta"]) == (
        "resurfaced", "research_more", None,
    )


@pytest.mark.asyncio
async def test_failed_run_with_null_started_at_and_naive_block_time(clean_db: AsyncSession):
    """Hardening: a legacy failed row with no started_at must not hide a
    newer one, and a naive ``at`` in the block must not 500 the page."""
    session = clean_db
    dossier = await _watching(session, {"rescan": {
        "trigger": "watch", "previous_dossier_id": "p", "resurfaced": False,
        "reason": "unchanged", "score_delta": 0.0, "new_evidence_count": 0,
        "run_id": "r", "at": T0.replace(tzinfo=None).isoformat(),
    }})
    legacy = await _failed_rescan(session, dossier, at=T0 + timedelta(days=1), error="legacy")
    legacy.started_at = None
    legacy.completed_at = None
    await session.commit()
    real = await _failed_rescan(session, dossier, at=T0 + timedelta(hours=1), error="real")

    async with _make_client(session) as client:
        resp = await client.get("/dossiers/watching")

    assert resp.status_code == 200
    [row] = resp.json()
    assert row["last_rescan"]["run_id"] == real.id and row["last_rescan"]["error"] == "real"


@pytest.mark.asyncio
async def test_malformed_rescan_block_is_ignored(clean_db: AsyncSession):
    session = clean_db
    await _watching(session, {"rescan": {"at": "not a date", "resurfaced": False}})

    async with _make_client(session) as client:
        [row] = (await client.get("/dossiers/watching")).json()

    assert row["last_rescan"] is None
