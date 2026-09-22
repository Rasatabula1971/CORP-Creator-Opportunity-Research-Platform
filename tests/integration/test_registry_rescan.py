"""Integration tests for the registry re-scan scheduler (CORP1 Stage 5,
T10) against real Postgres.

The frozen test requirement is a time-travel test: a watched dossier
past its niche's recheck date gets re-scored, a fresh one does not.
"Mocked clock" here means dependency-injecting ``now`` into
rescan_watched_dossiers()/find_due_watched_dossiers() rather than
monkeypatching datetime.now() globally -- deterministic, and it can't
bleed into any other test running in the same process.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche
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
    RegistryRescanScheduler,
    RescanDeferredError,
    RescannerHandle,
    find_due_watched_dossiers,
    rescan_watched_dossiers,
)
from corp.workers.watch_rescan import ResurfaceDecision, WatchRescanConfig

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


# ---------- R8: clock only on success, savepoint per dossier, unchanged stays WATCHING ----------


@pytest.mark.asyncio
async def test_unchanged_content_stays_watching(clean_db: AsyncSession):
    """First re-scan: fixture content differs from a real regeneration, so it
    resurfaces. Second re-scan with nothing changed: identical content, the
    new row stays WATCHING and is counted as unchanged."""
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso", next_recheck_at=NOW - timedelta(days=1))
    run = await _make_run(session, creator.id)
    opp = await _make_scored_opportunity(session, creator, run)
    await _make_watching_dossier(session, creator, niche, opp)

    first = await rescan_watched_dossiers(session, RULES_PATH, now=NOW)
    await session.commit()
    assert (first.rescored, first.unchanged) == (1, 0)
    latest = (await session.execute(
        select(Dossier).where(Dossier.superseded_at.is_(None))
    )).scalar_one()
    assert latest.status == DossierStatus.PENDING_REVIEW

    # Human parks it again; clock runs out again; evidence has not moved.
    latest.status = DossierStatus.WATCHING
    niche.next_recheck_at = NOW - timedelta(days=1)
    await session.commit()
    later = NOW + timedelta(days=1)

    second = await rescan_watched_dossiers(session, RULES_PATH, now=later)
    await session.commit()
    assert (second.rescored, second.unchanged, second.failed) == (1, 1, 0)
    newest = (await session.execute(
        select(Dossier).where(Dossier.superseded_at.is_(None))
    )).scalar_one()
    assert newest.id != latest.id
    assert newest.status == DossierStatus.WATCHING
    await session.refresh(niche)
    assert niche.next_recheck_at == later + timedelta(days=90)


@pytest.mark.asyncio
async def test_failed_dossier_is_retried_soon_not_deferred_a_quarter(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso", next_recheck_at=NOW - timedelta(days=1))
    run = await _make_run(session, creator.id)
    opp = await _make_scored_opportunity(session, creator, run)
    await _make_watching_dossier(session, creator, niche, opp)
    await supersede(session, OpportunityScore, OpportunityScore.creator_id == creator.id)
    await session.commit()
    before = niche.last_researched_at

    stats = await rescan_watched_dossiers(session, RULES_PATH, now=NOW, retry_days=1)
    await session.commit()

    assert (stats.checked, stats.rescored, stats.failed) == (1, 0, 1)
    await session.refresh(niche)
    assert niche.last_researched_at == before  # not a successful scan
    assert niche.next_recheck_at == NOW + timedelta(days=1)  # retry tomorrow, not in 90 days


@pytest.mark.asyncio
async def test_database_error_in_one_dossier_does_not_poison_the_batch(
    clean_db: AsyncSession, monkeypatch
):
    """A DB-level failure (not just a Python exception before flush) inside
    one dossier's regeneration must roll back only that dossier's savepoint
    and leave the session usable for the next one and for the final commit."""
    from corp.workers.dossier.generator import DossierGenerator

    session = clean_db
    creator_a = await _make_creator(session, "Creator A")
    niche_a = await _make_niche(session, "Home Espresso A", next_recheck_at=NOW - timedelta(days=1))
    run_a = await _make_run(session, creator_a.id)
    opp_a = await _make_scored_opportunity(session, creator_a, run_a)
    await _make_watching_dossier(session, creator_a, niche_a, opp_a)

    creator_b = await _make_creator(session, "Creator B")
    niche_b = await _make_niche(session, "Home Espresso B", next_recheck_at=NOW - timedelta(days=1))
    run_b = await _make_run(session, creator_b.id)
    opp_b = await _make_scored_opportunity(session, creator_b, run_b)
    await _make_watching_dossier(session, creator_b, niche_b, opp_b)

    original = DossierGenerator.generate_and_persist

    async def flaky(self: DossierGenerator, creator_id: str, niche_id: str) -> Dossier:
        if creator_id == creator_a.id:
            # Foreign-key violation surfaces from the database at flush.
            self._session.add(Dossier(
                creator_id="no-such-creator", niche_id=niche_id,
                opportunity_score_id="no-such-score", content={},
            ))
            await self._session.flush()
        return await original(self, creator_id, niche_id)

    monkeypatch.setattr(DossierGenerator, "generate_and_persist", flaky)

    stats = await rescan_watched_dossiers(session, RULES_PATH, now=NOW)
    await session.commit()  # session must still be usable after A's DB error

    assert (stats.checked, stats.rescored, stats.failed) == (2, 1, 1)
    a_rows = (await session.execute(
        select(Dossier).where(Dossier.creator_id == creator_a.id)
    )).scalars().all()
    assert len(a_rows) == 1 and a_rows[0].superseded_at is None  # A untouched
    b_rows = (await session.execute(
        select(Dossier).where(Dossier.creator_id == creator_b.id)
    )).scalars().all()
    assert len(b_rows) == 2
    await session.refresh(niche_a)
    await session.refresh(niche_b)
    assert niche_a.next_recheck_at == NOW + timedelta(days=1)
    assert niche_b.next_recheck_at == NOW + timedelta(days=90)


# ---------- R12c: the scheduler re-researches through a WatchRescanner ----------


@dataclass
class _Outcome:
    run_id: str
    previous_dossier_id: str
    dossier_id: str
    status: DossierStatus
    decision: ResurfaceDecision


class FakeRescanner:
    """Stands in for WatchRescanner: supersedes the watched dossier with a
    new version whose status follows the scripted decision, or raises."""

    def __init__(
        self, session: AsyncSession, *, resurface: bool = True, fail_for: set[str] | None = None
    ) -> None:
        self.session, self.resurface, self.fail_for = session, resurface, fail_for or set()
        self.calls: list[str] = []

    async def rescan(self, dossier_id: str, *, trigger: str) -> _Outcome:
        self.calls.append(dossier_id)
        if dossier_id in self.fail_for:
            raise RuntimeError("scripted rescan failure")
        old = await self.session.get(Dossier, dossier_id)
        assert old is not None and trigger == "watch"
        old.superseded_at = NOW
        new = Dossier(
            creator_id=old.creator_id, niche_id=old.niche_id,
            opportunity_score_id=old.opportunity_score_id, content={"v": 2},
            status=DossierStatus.PENDING_REVIEW if self.resurface else DossierStatus.WATCHING,
        )
        self.session.add(new)
        await self.session.flush()
        return _Outcome("run", old.id, new.id, new.status,
                        ResurfaceDecision(self.resurface, "scripted", 0.1, 0))


async def _due_watching(
    session: AsyncSession, name: str, *, with_campaign: bool = False
) -> tuple[Dossier, Niche]:
    creator = await _make_creator(session, f"Creator {name}")
    niche = await _make_niche(session, name, next_recheck_at=NOW - timedelta(days=1))
    if with_campaign:
        campaign = Campaign(name=f"Campaign {name}")
        session.add(campaign)
        await session.flush()
        session.add(CampaignNiche(campaign_id=campaign.id, niche_id=niche.id))
        await session.flush()
    run = await _make_run(session, creator.id)
    opp = await _make_scored_opportunity(session, creator, run)
    return await _make_watching_dossier(session, creator, niche, opp), niche


@pytest.mark.asyncio
async def test_rescanner_path_resurfaces_and_advances_clock(clean_db: AsyncSession):
    session = clean_db
    dossier, niche = await _due_watching(session, "Home Espresso")
    rescanner = FakeRescanner(session, resurface=True)

    stats = await rescan_watched_dossiers(
        session, RULES_PATH, now=NOW, rescanner=rescanner, recheck_days=90,  # type: ignore[arg-type]
    )

    assert rescanner.calls == [dossier.id]
    assert (stats.checked, stats.rescored, stats.resurfaced, stats.unchanged, stats.failed) == (
        1, 1, 1, 0, 0,
    )
    await session.refresh(niche)
    assert niche.last_researched_at == NOW and niche.next_recheck_at == NOW + timedelta(days=90)


@pytest.mark.asyncio
async def test_rescanner_path_unchanged_counts_and_stays_watching(clean_db: AsyncSession):
    session = clean_db
    await _due_watching(session, "Home Espresso")
    rescanner = FakeRescanner(session, resurface=False)

    stats = await rescan_watched_dossiers(
        session, RULES_PATH, now=NOW, rescanner=rescanner,  # type: ignore[arg-type]
    )

    assert (stats.rescored, stats.resurfaced, stats.unchanged) == (1, 0, 1)
    active = (await session.execute(
        select(Dossier).where(Dossier.superseded_at.is_(None))
    )).scalar_one()
    assert active.status == DossierStatus.WATCHING


@pytest.mark.asyncio
async def test_per_tick_cap_defers_the_rest_longest_overdue_first(clean_db: AsyncSession):
    session = clean_db
    _, older = await _due_watching(session, "Older")
    older.next_recheck_at = NOW - timedelta(days=30)
    await _due_watching(session, "Newer")
    await session.commit()
    rescanner = FakeRescanner(session)

    stats = await rescan_watched_dossiers(
        session, RULES_PATH, now=NOW, rescanner=rescanner, max_dossiers=1,  # type: ignore[arg-type]
    )

    assert (stats.checked, stats.rescored, stats.deferred) == (2, 1, 1)
    processed = await session.get(Dossier, rescanner.calls[0])
    assert processed is not None and processed.niche_id == older.id
    # The deferred one is untouched and still due next tick.
    still_due = await find_due_watched_dossiers(session, now=NOW)
    assert len(still_due) == 1 and still_due[0].niche_id != older.id


@pytest.mark.asyncio
async def test_busy_campaign_is_skipped_and_stays_due(clean_db: AsyncSession):
    session = clean_db
    dossier, _ = await _due_watching(session, "Busy", with_campaign=True)
    rescanner = FakeRescanner(session)

    stats = await rescan_watched_dossiers(
        session, RULES_PATH, now=NOW, rescanner=rescanner,  # type: ignore[arg-type]
        is_busy=lambda campaign_id, creator_id: campaign_id is not None,
    )

    assert rescanner.calls == []
    assert (stats.checked, stats.deferred, stats.rescored) == (1, 1, 0)
    assert [d.id for d in await find_due_watched_dossiers(session, now=NOW)] == [dossier.id]


@pytest.mark.asyncio
async def test_busy_creator_is_skipped_even_without_a_campaign(clean_db: AsyncSession):
    """A console job already researching the creator (still WATCHING, so the
    rescanner's precondition would not catch it) must not be raced."""
    session = clean_db
    dossier, _ = await _due_watching(session, "Creator job")
    rescanner = FakeRescanner(session)
    seen: list[tuple[str | None, str]] = []

    def is_busy(campaign_id: str | None, creator_id: str) -> bool:
        seen.append((campaign_id, creator_id))
        return creator_id == dossier.creator_id

    stats = await rescan_watched_dossiers(
        session, RULES_PATH, now=NOW, rescanner=rescanner, is_busy=is_busy,  # type: ignore[arg-type]
    )

    assert seen == [(None, dossier.creator_id)]
    assert rescanner.calls == [] and stats.deferred == 1


class RollbackRescanner(FakeRescanner):
    """Commits an early stage, then hits a real DB error and rolls the shared
    session back -- ResearchOrchestrator._persist_after_crash's branch (ADR-0061
    round 2). That expires every loaded row, primary keys included."""

    async def rescan(self, dossier_id: str, *, trigger: str) -> _Outcome:
        if dossier_id not in self.fail_for:
            return await super().rescan(dossier_id, trigger=trigger)
        self.calls.append(dossier_id)
        await self.session.commit()
        self.session.add(Dossier(
            creator_id="no-such-creator", niche_id="x", opportunity_score_id="y", content={},
        ))
        try:
            await self.session.flush()
        except Exception:  # noqa: BLE001 -- FK violation is the point
            await self.session.rollback()
        raise RuntimeError("stage crashed and the session was rolled back")


@pytest.mark.asyncio
async def test_rescanner_rollback_still_retries_and_batch_continues(clean_db: AsyncSession):
    """Design 3.7-3 for the rollback case: the failed dossier's retry clock is
    still recorded and the next dossier is still processed."""
    session = clean_db
    bad, bad_niche = await _due_watching(session, "Bad")
    bad_niche.next_recheck_at = NOW - timedelta(days=30)  # processed first
    good, good_niche = await _due_watching(session, "Good")
    await session.commit()
    bad_id, good_id = bad.id, good.id  # the rollback expires these rows
    rescanner = RollbackRescanner(session, fail_for={bad_id})

    stats = await rescan_watched_dossiers(
        session, RULES_PATH, now=NOW, rescanner=rescanner, retry_days=1,  # type: ignore[arg-type]
    )

    assert rescanner.calls == [bad_id, good_id]
    assert (stats.rescored, stats.failed) == (1, 1)
    bad = (await session.execute(select(Dossier).where(Dossier.id == bad_id))).scalar_one()
    niches = {n.canonical_name: n for n in (await session.execute(select(Niche))).scalars()}
    assert niches["Bad"].next_recheck_at == NOW + timedelta(days=1)
    assert niches["Good"].next_recheck_at == NOW + timedelta(days=90)
    assert bad.superseded_at is None and bad.status == DossierStatus.WATCHING


@pytest.mark.asyncio
async def test_cap_does_not_apply_to_the_re_render_fallback(clean_db: AsyncSession):
    """Without a rescanner the cheap R8 path must clear any backlog in one
    tick (T10's 24-hour invariant); the cap bounds LLM cost only."""
    session = clean_db
    for name in ("A", "B"):
        await _due_watching(session, name)
    await session.commit()

    stats = await rescan_watched_dossiers(session, RULES_PATH, now=NOW, max_dossiers=1)

    assert (stats.checked, stats.rescored, stats.deferred) == (2, 2, 0)


@pytest.mark.asyncio
async def test_rescanner_failure_retries_soon_and_batch_continues(clean_db: AsyncSession):
    session = clean_db
    bad, bad_niche = await _due_watching(session, "Bad")
    good, _ = await _due_watching(session, "Good")
    rescanner = FakeRescanner(session, fail_for={bad.id})

    stats = await rescan_watched_dossiers(
        session, RULES_PATH, now=NOW, rescanner=rescanner, retry_days=1,  # type: ignore[arg-type]
    )

    assert set(rescanner.calls) == {bad.id, good.id}
    assert (stats.rescored, stats.failed) == (1, 1)
    await session.refresh(bad_niche)
    assert bad_niche.next_recheck_at == NOW + timedelta(days=1)
    await session.refresh(bad)
    assert bad.superseded_at is None and bad.status == DossierStatus.WATCHING


@pytest.mark.asyncio
async def test_scheduler_tick_defers_when_factory_raises(clean_db: AsyncSession):
    """Design 3.4: every provider cooling -> the tick touches nothing."""
    from tests.conftest import async_test_session

    session = clean_db
    dossier, niche = await _due_watching(session, "Cooling")
    before = niche.next_recheck_at

    async def factory(_session: AsyncSession, _cfg: WatchRescanConfig) -> RescannerHandle | None:
        raise RescanDeferredError("all providers cooling")

    scheduler = RegistryRescanScheduler(
        async_test_session, RULES_PATH, rescanner_factory=factory, interval_seconds=1,
    )
    await scheduler._tick()

    assert scheduler._consecutive_failures == 0
    await session.refresh(niche)
    await session.refresh(dossier)
    assert niche.next_recheck_at == before and dossier.superseded_at is None


@pytest.mark.asyncio
async def test_scheduler_tick_uses_factory_rescanner_and_closes_it(clean_db: AsyncSession):
    from tests.conftest import async_test_session

    session = clean_db
    dossier, _ = await _due_watching(session, "Factory")
    closed: list[bool] = []
    created: list[FakeRescanner] = []

    async def factory(tick_session: AsyncSession, cfg: WatchRescanConfig) -> RescannerHandle | None:
        assert cfg.max_dossiers_per_tick == 3  # the scheduler hands its config over
        rescanner = FakeRescanner(tick_session)
        created.append(rescanner)

        async def aclose() -> None:
            closed.append(True)

        return RescannerHandle(rescanner=rescanner, aclose=aclose)  # type: ignore[arg-type]

    scheduler = RegistryRescanScheduler(
        async_test_session, RULES_PATH, rescanner_factory=factory, interval_seconds=1,
    )
    await scheduler._tick()

    assert created and created[0].calls == [dossier.id]
    assert closed == [True]
    session.expire_all()
    active = (await session.execute(
        select(Dossier).where(Dossier.superseded_at.is_(None))
    )).scalar_one()
    assert active.status == DossierStatus.PENDING_REVIEW
