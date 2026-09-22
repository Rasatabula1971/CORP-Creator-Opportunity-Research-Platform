"""R12a: WatchRescanner -- re-research a (creator, niche) dossier and produce
a new version. Collaborators (niche driller, creator researcher, ideator)
are faked; the DB-side chain (dossier supersession, decision, run
bookkeeping, creator-status mirror, failure restore) runs for real."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.dossier import Dossier, DossierStatus
from corp.core.models.evidence import (
    AccessMethod,
    ComplianceStatus,
    Evidence,
    EvidenceOrigin,
    EvidenceType,
)
from corp.core.models.intelligence import ProblemCluster, ProblemClusterMember, ProblemObservation
from corp.core.models.niche import Niche
from corp.core.models.scoring import ConfidenceBand, CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun, RunType
from corp.workers.intelligence.runs import supersede
from corp.workers.watch_rescan import (
    RescanError,
    WatchRescanConfig,
    WatchRescanner,
    decide_resurface,
)

RULES_PATH = "rules/scoring.yaml"
CFG = WatchRescanConfig(resurface_min_score_delta=0.05, resurface_min_new_evidence=10)


# ---------- decide_resurface (pure) ----------


def _d(**kw):  # noqa: ANN001, ANN202 -- test helper
    base = dict(
        old_score=0.60, old_band=ConfidenceBand.MEDIUM, new_score=0.60,
        new_band=ConfidenceBand.MEDIUM, new_evidence_count=0,
        content_unchanged=False, always=False,
    )
    base.update(kw)
    return decide_resurface(CFG, **base)


def test_decide_always_resurfaces_for_research_more():
    d = _d(always=True, content_unchanged=True)
    assert d.resurfaced and "reviewer" in d.reason


def test_decide_identical_content_never_resurfaces():
    assert not _d(content_unchanged=True, new_score=0.9).resurfaced


def test_decide_score_delta_threshold():
    assert not _d(new_score=0.64).resurfaced
    d = _d(new_score=0.65)
    assert d.resurfaced and d.score_delta == 0.05 and "score +0.05" in d.reason


def test_decide_band_improvement_alone_resurfaces():
    d = _d(new_band=ConfidenceBand.HIGH)
    assert d.resurfaced and "medium → high" in d.reason


def test_decide_new_evidence_only_when_score_did_not_fall():
    assert _d(new_evidence_count=10).resurfaced
    assert not _d(new_evidence_count=10, new_score=0.59).resurfaced
    assert not _d(new_evidence_count=9).resurfaced


def test_decide_no_previous_score_uses_evidence_only():
    d = _d(old_score=None, old_band=None, new_evidence_count=12)
    assert d.resurfaced and d.score_delta is None


# ---------- fixtures ----------


class FakeDriller:
    def __init__(self, session: AsyncSession, *, fail: bool = False) -> None:
        self.session, self.fail, self.calls = session, fail, []

    async def research_more(self, niche_id: str, campaign_id: str) -> ResearchRun:
        self.calls.append((niche_id, campaign_id))
        run = ResearchRun(
            creator_id=None, campaign_id=campaign_id, niche_id=niche_id,
            run_type=RunType.NICHE_DISCOVERY.value, status="failed" if self.fail else "completed",
            error_message="drill blew up" if self.fail else None,
        )
        self.session.add(run)
        await self.session.flush()
        return run


class _Report:
    def __init__(self, runs: list[ResearchRun], final_status: str) -> None:
        self.runs, self.final_status = runs, final_status


class FakeResearcher:
    """Stands in for ResearchOrchestrator: writes a NEW active OpportunityScore
    (superseding the old) with the configured score/band, like a real
    scoring stage would, and reports the creator at HUMAN_REVIEW."""

    def __init__(
        self, session: AsyncSession, *, new_score: float = 0.60,
        new_band: ConfidenceBand = ConfidenceBand.MEDIUM, fail_stage: str | None = None,
    ) -> None:
        self.session, self.new_score, self.new_band, self.fail_stage = (
            session, new_score, new_band, fail_stage,
        )
        self.calls: list[tuple[str, bool]] = []

    async def run(self, creator_id: str, *, skip_collect: bool = False) -> _Report:
        self.calls.append((creator_id, skip_collect))
        if self.fail_stage:
            run = ResearchRun(
                creator_id=creator_id, status="failed",
                config_snapshot={"pipeline": self.fail_stage}, error_message="boom",
            )
            self.session.add(run)
            await self.session.flush()
            return _Report([run], "watching")
        cluster = (await self.session.execute(
            select(ProblemCluster).where(ProblemCluster.creator_id == creator_id)
        )).scalars().first()
        assert cluster is not None
        await supersede(self.session, OpportunityScore, OpportunityScore.creator_id == creator_id)
        run = ResearchRun(creator_id=creator_id, status="completed",
                          config_snapshot={"pipeline": "scoring"})
        self.session.add(run)
        await self.session.flush()
        self.session.add(OpportunityScore(
            creator_id=creator_id, problem_cluster_id=cluster.id,
            component_scores={"frequency": self.new_score}, aggregate_score=self.new_score,
            computed_hash=f"rescored-{self.new_score}", confidence_band=self.new_band,
            rule_version="v1", model_version="fake", research_run_id=run.id,
        ))
        await self.session.flush()
        creator = await self.session.get(Creator, creator_id)
        assert creator is not None
        creator.status = CreatorStatus.HUMAN_REVIEW
        await self.session.flush()
        return _Report([run], "human_review")


class FakeIdeator:
    def __init__(self, session: AsyncSession) -> None:
        self.session, self.calls = session, []

    async def generate(self, creator_id: str) -> ResearchRun:
        self.calls.append(creator_id)
        run = ResearchRun(creator_id=creator_id, status="completed",
                          config_snapshot={"pipeline": "product_ideation"})
        self.session.add(run)
        await self.session.flush()
        return run


async def _seed(
    session: AsyncSession, *, dossier_status: DossierStatus = DossierStatus.WATCHING,
    creator_status: CreatorStatus = CreatorStatus.WATCHING, old_score: float = 0.60,
    with_campaign: bool = True,
) -> Dossier:
    creator = Creator(name="R12a Creator", niche="espresso", discovery_source="seed",
                      status=creator_status)
    session.add(creator)
    await session.flush()
    niche = Niche(canonical_name="Home Espresso R12a")
    session.add(niche)
    await session.flush()
    if with_campaign:
        campaign = Campaign(name="R12a")
        session.add(campaign)
        await session.flush()
        session.add(CampaignNiche(campaign_id=campaign.id, niche_id=niche.id,
                                  status=CampaignNicheStatus.SELECTED))
    run = ResearchRun(creator_id=creator.id, status="completed")
    session.add(run)
    await session.flush()
    cluster = ProblemCluster(creator_id=creator.id, label="Grinder confusion", frequency=3,
                             evidence_strength=0.8)
    session.add(cluster)
    await session.flush()
    ev = Evidence(source_type="comment", source_id="r12a_cmt", source_platform="youtube",
                  raw_text="I wish there was a grinder chart", access_method=AccessMethod.OFFICIAL,
                  compliance_status=ComplianceStatus.COMPLIANT, research_run_id=run.id,
                  origin=EvidenceOrigin.OBSERVATION, evidence_type=EvidenceType.PROBLEM,
                  collected_at=datetime.now(UTC) - timedelta(days=100))
    session.add(ev)
    await session.flush()
    obs = ProblemObservation(evidence_id=ev.id, text=ev.raw_text, is_inferred=False,
                             extraction_prompt_version="v1", model_version="fx")
    session.add(obs)
    await session.flush()
    session.add(ProblemClusterMember(cluster_id=cluster.id, observation_id=obs.id,
                                     similarity_score=0.9))
    session.add(CreatorScore(creator_id=creator.id, component_scores={"frequency": old_score},
                             aggregate_score=old_score, computed_hash="cs",
                             confidence_band=ConfidenceBand.MEDIUM, rule_version="v1",
                             model_version="fx"))
    opp = OpportunityScore(creator_id=creator.id, problem_cluster_id=cluster.id,
                           component_scores={"frequency": old_score}, aggregate_score=old_score,
                           computed_hash="os", confidence_band=ConfidenceBand.MEDIUM,
                           rule_version="v1", model_version="fx", research_run_id=run.id)
    session.add(opp)
    await session.flush()
    dossier = Dossier(creator_id=creator.id, niche_id=niche.id, opportunity_score_id=opp.id,
                      content={"score_band": "old"}, status=dossier_status,
                      generated_at=datetime.now(UTC) - timedelta(days=91))
    session.add(dossier)
    await session.commit()
    return dossier


def _rescanner(session: AsyncSession, researcher: FakeResearcher, driller: FakeDriller,
               ideator: FakeIdeator | None, cfg: WatchRescanConfig = CFG) -> WatchRescanner:
    return WatchRescanner(session, driller=driller, researcher=researcher, ideator=ideator,
                          scoring_rules_path=RULES_PATH, config=cfg)


async def _new_evidence(session: AsyncSession, creator_id: str, n: int) -> None:
    run = ResearchRun(creator_id=creator_id, status="completed")
    session.add(run)
    await session.flush()
    for i in range(n):
        session.add(Evidence(source_type="comment", source_id=f"r12a_new_{i}",
                             source_platform="youtube", raw_text=f"new {i}",
                             access_method=AccessMethod.OFFICIAL,
                             compliance_status=ComplianceStatus.COMPLIANT,
                             research_run_id=run.id, origin=EvidenceOrigin.OBSERVATION,
                             evidence_type=EvidenceType.PROBLEM))
    await session.flush()


# ---------- the chain ----------


@pytest.mark.asyncio
async def test_watch_rescan_resurfaces_when_score_strengthened(clean_db: AsyncSession):
    session = clean_db
    old = await _seed(session)
    driller, researcher, ideator = (
        FakeDriller(session), FakeResearcher(session, new_score=0.72), FakeIdeator(session),
    )

    rescanner = _rescanner(session, researcher, driller, ideator)
    outcome = await rescanner.rescan(old.id, trigger="watch")
    await session.commit()

    assert driller.calls and researcher.calls == [(old.creator_id, False)]
    assert ideator.calls == [old.creator_id]
    new = await session.get(Dossier, outcome.dossier_id)
    assert new is not None and new.id != old.id
    await session.refresh(new)  # persisted state, not the identity map
    assert new.status == DossierStatus.PENDING_REVIEW
    assert outcome.decision.resurfaced and "score +0.12" in outcome.decision.reason
    assert new.content["rescan"]["previous_dossier_id"] == old.id
    assert new.content["rescan"]["resurfaced"] is True
    await session.refresh(old)
    assert old.superseded_at is not None
    creator = await session.get(Creator, old.creator_id)
    assert creator is not None and creator.status == CreatorStatus.HUMAN_REVIEW
    run = await session.get(ResearchRun, outcome.run_id)
    assert run is not None and run.run_type == RunType.WATCH_RESCAN.value
    assert run.status == "completed" and run.stats["extra"]["resurfaced"] is True


@pytest.mark.asyncio
async def test_watch_rescan_unchanged_stays_watching(clean_db: AsyncSession):
    session = clean_db
    old = await _seed(session)
    researcher = FakeResearcher(session, new_score=0.60)

    rescanner = _rescanner(session, researcher, FakeDriller(session), FakeIdeator(session))
    outcome = await rescanner.rescan(old.id, trigger="watch")
    await session.commit()

    new = await session.get(Dossier, outcome.dossier_id)
    assert new is not None and new.status == DossierStatus.WATCHING
    assert not outcome.decision.resurfaced and outcome.decision.reason.startswith("unchanged")
    creator = await session.get(Creator, old.creator_id)
    assert creator is not None and creator.status == CreatorStatus.WATCHING  # mirror (R12b)


@pytest.mark.asyncio
async def test_watch_rescan_resurfaces_on_new_evidence_volume(clean_db: AsyncSession):
    session = clean_db
    old = await _seed(session)
    await _new_evidence(session, old.creator_id, 10)
    await session.commit()

    outcome = await _rescanner(
        session, FakeResearcher(session, new_score=0.60), FakeDriller(session), FakeIdeator(session)
    ).rescan(old.id, trigger="watch")
    await session.commit()

    assert outcome.decision.resurfaced
    assert outcome.decision.new_evidence_count == 10
    assert "10 new evidence rows" in outcome.decision.reason


@pytest.mark.asyncio
async def test_research_more_always_resurfaces_and_parks_creator_during_research(
    clean_db: AsyncSession,
):
    session = clean_db
    old = await _seed(session, dossier_status=DossierStatus.RESEARCH_MORE_IN_PROGRESS,
                      creator_status=CreatorStatus.HUMAN_REVIEW)
    researcher = FakeResearcher(session, new_score=0.60)

    rescanner = _rescanner(session, researcher, FakeDriller(session), FakeIdeator(session))
    outcome = await rescanner.rescan(old.id, trigger="research_more")
    await session.commit()

    new = await session.get(Dossier, outcome.dossier_id)
    assert new is not None and new.status == DossierStatus.PENDING_REVIEW
    assert "reviewer" in outcome.decision.reason
    rows = (
        await session.execute(select(Dossier).where(Dossier.creator_id == old.creator_id))
    ).scalars().all()
    active = [r for r in rows if r.superseded_at is None]
    assert all(r.status != DossierStatus.RESEARCH_MORE_IN_PROGRESS for r in active)


@pytest.mark.asyncio
async def test_failed_stage_restores_research_more_dossier_and_records_stage(
    clean_db: AsyncSession,
):
    session = clean_db
    old = await _seed(session, dossier_status=DossierStatus.RESEARCH_MORE_IN_PROGRESS,
                      creator_status=CreatorStatus.HUMAN_REVIEW)
    researcher = FakeResearcher(session, fail_stage="clustering")

    with pytest.raises(RescanError, match="clustering"):
        await _rescanner(session, researcher, FakeDriller(session), FakeIdeator(session)).rescan(
            old.id, trigger="research_more"
        )
    await session.commit()

    await session.refresh(old)
    assert old.superseded_at is None
    assert old.status == DossierStatus.PENDING_REVIEW  # never stuck in progress
    run = (await session.execute(
        select(ResearchRun).where(ResearchRun.run_type == RunType.WATCH_RESCAN.value)
    )).scalar_one()
    assert run.status == "failed" and "creator_research" in (run.error_message or "")


@pytest.mark.asyncio
async def test_failed_drill_leaves_watched_dossier_active(clean_db: AsyncSession):
    session = clean_db
    old = await _seed(session)

    with pytest.raises(RescanError, match="research_more"):
        await _rescanner(
            session, FakeResearcher(session), FakeDriller(session, fail=True), FakeIdeator(session)
        ).rescan(old.id, trigger="watch")
    await session.commit()

    await session.refresh(old)
    assert old.superseded_at is None and old.status == DossierStatus.WATCHING
    assert [d.id for d in (await session.execute(select(Dossier))).scalars().all()] == [old.id]


@pytest.mark.asyncio
async def test_no_campaign_skips_niche_drill_but_still_rescans(clean_db: AsyncSession):
    session = clean_db
    old = await _seed(session, with_campaign=False)
    driller = FakeDriller(session)

    outcome = await _rescanner(
        session, FakeResearcher(session, new_score=0.80), driller, FakeIdeator(session)
    ).rescan(old.id, trigger="watch")
    await session.commit()

    assert driller.calls == []
    assert outcome.decision.resurfaced


@pytest.mark.asyncio
async def test_recollect_creator_off_rerenders_only(clean_db: AsyncSession):
    session = clean_db
    old = await _seed(session)
    researcher = FakeResearcher(session, new_score=0.99)
    cfg = WatchRescanConfig(recollect_creator=False)

    outcome = await _rescanner(session, researcher, FakeDriller(session), None, cfg).rescan(
        old.id, trigger="watch"
    )
    await session.commit()

    assert researcher.calls == []  # creator chain not run
    new = await session.get(Dossier, outcome.dossier_id)
    assert new is not None and new.status == DossierStatus.WATCHING  # same score → unchanged


@pytest.mark.asyncio
async def test_refuses_creator_not_in_a_researchable_status(clean_db: AsyncSession):
    """An APPROVED creator (multi-niche precedence) must not be silently
    re-researched with skipped status moves."""
    session = clean_db
    old = await _seed(session, creator_status=CreatorStatus.APPROVED)

    with pytest.raises(RescanError, match="precondition"):
        await _rescanner(
            session, FakeResearcher(session), FakeDriller(session), FakeIdeator(session)
        ).rescan(old.id, trigger="watch")
    await session.commit()

    await session.refresh(old)
    assert old.superseded_at is None and old.status == DossierStatus.WATCHING


class RollbackResearcher:
    """Reproduces ResearchOrchestrator._persist_after_crash's rollback branch:
    commits (making the watch_rescan run persistent), then rolls the shared
    session back -- which expires every loaded attribute, primary keys
    included -- and raises."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(self, creator_id: str, *, skip_collect: bool = False) -> _Report:
        await self.session.commit()
        await self.session.rollback()
        raise RuntimeError("stage crashed and the session was rolled back")


@pytest.mark.asyncio
async def test_rollback_in_researcher_still_fails_run_and_restores_dossier(
    clean_db: AsyncSession,
):
    session = clean_db
    old = await _seed(session, dossier_status=DossierStatus.RESEARCH_MORE_IN_PROGRESS,
                      creator_status=CreatorStatus.HUMAN_REVIEW)

    with pytest.raises(RuntimeError, match="rolled back"):
        await _rescanner(
            session, RollbackResearcher(session), FakeDriller(session), FakeIdeator(session)
        ).rescan(old.id, trigger="research_more")
    await session.commit()

    await session.refresh(old)
    assert old.status == DossierStatus.PENDING_REVIEW  # restored despite the rollback
    creator = await session.get(Creator, old.creator_id)
    assert creator is not None
    await session.refresh(creator)
    assert creator.status == CreatorStatus.HUMAN_REVIEW  # un-parked with the dossier
    run = (await session.execute(
        select(ResearchRun).where(ResearchRun.run_type == RunType.WATCH_RESCAN.value)
    )).scalar_one()
    assert run.status == "failed" and "creator_research" in (run.error_message or "")
