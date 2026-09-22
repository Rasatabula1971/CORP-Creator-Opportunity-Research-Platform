"""Re-research a (creator, niche) dossier and produce a new version (R12).

One worker for both triggers the spec ties to re-research:

* **Research More** (dossier gate): "drills one level deeper into the niche
  and re-queries all evidence sources for that specific niche, then produces
  an updated dossier." Always resurfaces to PENDING_REVIEW -- the human
  asked for it.
* **Watch re-scan** (scheduler, R12c): "re-scored on the same 90-day cycle,
  so it can resurface on its own if the evidence strengthens." Resurfaces
  only when :func:`decide_resurface` says the evidence strengthened;
  otherwise the new version stays WATCHING.

The chain is: niche drill (``research_more``) -> creator re-research
(collect -> extract -> cluster -> intent -> score) -> product ideation ->
``generate_and_persist`` (supersedes the old dossier) -> resurface decision
-> creator status mirror. The three heavy collaborators are injected behind
small protocols so tests can fake them; :func:`build_watch_rescanner`
wires the real classes.

Failure semantics: the old dossier is never left in a dead state. Any
failure leaves it active; for the Research More trigger it is put back to
PENDING_REVIEW (it was ``research_more_in_progress``), and the
``watch_rescan`` run records which stage failed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign_niche import CampaignNiche
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.dossier import Dossier, DossierStatus
from corp.core.models.scoring import ConfidenceBand, OpportunityScore
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.core.scoring.niche_qualification import load_rules
from corp.core.state.gates import mirror_creator_status
from corp.core.state.transitions import advance
from corp.workers.dossier.generator import DossierGenerator
from corp.workers.intelligence.runs import PipelineStats, fail_run, finish_run, start_run

logger = logging.getLogger(__name__)

PIPELINE = "watch_rescan"

Trigger = Literal["watch", "research_more"]

_BAND_RANK = {
    ConfidenceBand.INSUFFICIENT: 0,
    ConfidenceBand.LOW: 1,
    ConfidenceBand.MEDIUM: 2,
    ConfidenceBand.HIGH: 3,
}

# Volatile keys that differ on every regeneration without the dossier's
# substance changing; excluded from the fingerprint.
_FINGERPRINT_IGNORE = frozenset({"generated_at", "rescan"})


def content_fingerprint(content: dict[str, Any]) -> str:
    """Stable hash of a dossier's content, ignoring timestamps and the rescan
    block itself, so a re-scan can tell "the evidence moved" from "nothing
    changed"."""
    stable = {k: v for k, v in content.items() if k not in _FINGERPRINT_IGNORE}
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


# ── Config ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class WatchRescanConfig:
    max_dossiers_per_tick: int = 3
    skip_when_provider_cooling: bool = True
    recollect_creator: bool = True
    resurface_min_score_delta: float = 0.05
    resurface_min_new_evidence: int = 10

    @classmethod
    def from_rules(cls, rules_path: str) -> WatchRescanConfig:
        block = load_rules(rules_path).get("watch_rescan", {}) or {}
        return cls(
            max_dossiers_per_tick=int(block.get("max_dossiers_per_tick", 3)),
            skip_when_provider_cooling=bool(block.get("skip_when_provider_cooling", True)),
            recollect_creator=bool(block.get("recollect_creator", True)),
            resurface_min_score_delta=float(block.get("resurface_min_score_delta", 0.05)),
            resurface_min_new_evidence=int(block.get("resurface_min_new_evidence", 10)),
        )


# ── Collaborator protocols ────────────────────────────────────────────


class NicheDriller(Protocol):
    async def research_more(self, niche_id: str, campaign_id: str) -> ResearchRun: ...


class StageReport(Protocol):
    final_status: str
    runs: list[ResearchRun]


class CreatorResearcher(Protocol):
    async def run(self, creator_id: str, *, skip_collect: bool = False) -> StageReport: ...


class Ideator(Protocol):
    async def generate(self, creator_id: str) -> ResearchRun: ...


# ── Decision ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ResurfaceDecision:
    resurfaced: bool
    reason: str
    score_delta: float | None
    new_evidence_count: int


def decide_resurface(
    cfg: WatchRescanConfig,
    *,
    old_score: float | None,
    old_band: ConfidenceBand | None,
    new_score: float,
    new_band: ConfidenceBand,
    new_evidence_count: int,
    content_unchanged: bool,
    always: bool,
) -> ResurfaceDecision:
    """Design §3.3 option C. Pure so it can be unit-tested exhaustively."""
    delta = None if old_score is None else round(new_score - old_score, 4)
    if always:
        return ResurfaceDecision(
            True, "research more requested by reviewer", delta, new_evidence_count
        )
    if content_unchanged:
        return ResurfaceDecision(
            False, "content identical to the watched dossier", delta, new_evidence_count
        )

    reasons: list[str] = []
    if delta is not None and delta >= cfg.resurface_min_score_delta:
        reasons.append(f"score {delta:+.2f}")
    if old_band is not None and _BAND_RANK[new_band] > _BAND_RANK[old_band]:
        reasons.append(f"confidence {old_band.value} → {new_band.value}")
    if new_evidence_count >= cfg.resurface_min_new_evidence and (delta is None or delta >= 0):
        reasons.append(f"{new_evidence_count} new evidence rows")
    if reasons:
        return ResurfaceDecision(True, "; ".join(reasons), delta, new_evidence_count)

    parts = []
    if delta is not None:
        parts.append(f"score {delta:+.2f}")
    parts.append(f"{new_evidence_count} new evidence rows")
    return ResurfaceDecision(False, "unchanged: " + ", ".join(parts), delta, new_evidence_count)


# ── Worker ────────────────────────────────────────────────────────────


class RescanError(RuntimeError):
    """A stage of the re-research chain failed; the message names it."""


_RESEARCHABLE = frozenset(
    {CreatorStatus.WATCHING, CreatorStatus.HUMAN_REVIEW, CreatorStatus.DISCOVERED}
)


@dataclass(frozen=True, slots=True)
class RescanOutcome:
    run_id: str
    previous_dossier_id: str
    dossier_id: str
    status: DossierStatus
    decision: ResurfaceDecision


class WatchRescanner:
    def __init__(
        self,
        session: AsyncSession,
        *,
        driller: NicheDriller,
        researcher: CreatorResearcher,
        ideator: Ideator | None,
        scoring_rules_path: str,
        config: WatchRescanConfig,
    ) -> None:
        self._session = session
        self._driller = driller
        self._researcher = researcher
        self._ideator = ideator
        self._scoring_rules_path = scoring_rules_path
        self._cfg = config

    async def rescan(self, dossier_id: str, *, trigger: Trigger) -> RescanOutcome:
        old = await self._session.get(Dossier, dossier_id)
        if old is None:
            raise ValueError(f"Dossier not found: {dossier_id}")
        if old.superseded_at is not None:
            raise ValueError(f"Dossier {dossier_id} is superseded; rescan the active version")
        creator = await self._session.get(Creator, old.creator_id)
        if creator is None:
            raise ValueError(f"Creator not found: {old.creator_id}")
        # The orchestrator's stage moves are non-strict: from any other status
        # it would silently skip them, re-supersede every score and report
        # success. Refuse instead of pretending (Stage 8 finding).
        if self._cfg.recollect_creator and creator.status not in _RESEARCHABLE:
            raise RescanError(
                f"precondition: creator {creator.id} is {creator.status.value}; "
                "re-research only from watching, human_review or discovered"
            )
        campaign_id = (
            await self._session.execute(
                select(CampaignNiche.campaign_id)
                .where(CampaignNiche.niche_id == old.niche_id)
                .order_by(CampaignNiche.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=creator.id,
            config={
                "trigger": trigger,
                "dossier_id": old.id,
                "niche_id": old.niche_id,
                "campaign_id": campaign_id,
                "recollect_creator": self._cfg.recollect_creator,
            },
            prompt_versions={},
            model_versions={},
            scope=RunScope.CREATOR,
            run_type=RunType.WATCH_RESCAN,
            campaign_id=campaign_id,
            niche_id=old.niche_id,
        )
        # Captured now: the orchestrator commits between stages, so this row
        # is persistent by the time a later stage can roll the session back
        # -- and a rollback expires every attribute, the primary key included.
        run_id = run.id
        stats = PipelineStats()
        stage = "start"
        try:
            # 1. Niche re-query (depth+1 drill across every NICHE adapter).
            if campaign_id is not None:
                stage = "research_more"
                drill = await self._driller.research_more(old.niche_id, campaign_id)
                stats.extra["research_more_run_id"] = drill.id
                if drill.status == "failed":
                    raise RescanError(f"research_more failed: {drill.error_message}")
            else:
                stats.extra["research_more_run_id"] = None
                logger.info(
                    "Dossier %s: niche %s has no campaign; skipping niche re-query",
                    old.id, old.niche_id,
                )

            # 2. Creator re-research. The orchestrator restarts from WATCHING;
            #    a creator still at HUMAN_REVIEW (Research More) is parked
            #    first -- a legal move, and honest: it is not reviewable while
            #    being re-researched.
            if self._cfg.recollect_creator:
                stage = "creator_research"
                if creator.status == CreatorStatus.HUMAN_REVIEW:
                    await advance(self._session, creator, CreatorStatus.WATCHING, strict=True)
                report = await self._researcher.run(creator.id, skip_collect=False)
                stats.extra["creator_research_runs"] = [r.id for r in report.runs]
                failed = [r for r in report.runs if r.status == "failed"]
                if failed:
                    pipeline = (failed[0].config_snapshot or {}).get("pipeline", "?")
                    raise RescanError(f"creator research stage {pipeline!r} failed")
                # The orchestrator commits between stages. With
                # expire_on_commit=False our objects stay attached and current,
                # so these are identity-map hits -- kept as a cheap guard for a
                # session factory configured otherwise.
                creator = await self._session.get(Creator, old.creator_id) or creator
                old = await self._session.get(Dossier, dossier_id) or old

            # 3. Product ideas (spec step 6) against the fresh clusters.
            if self._ideator is not None:
                stage = "product_ideation"
                ideas_run = await self._ideator.generate(creator.id)
                stats.extra["ideation_run_id"] = ideas_run.id
                if ideas_run.status == "failed":
                    raise RescanError(f"product ideation failed: {ideas_run.error_message}")

            # 4. New dossier version (supersedes the old one).
            stage = "dossier"
            generator = DossierGenerator(self._session, rules_path=self._scoring_rules_path)
            new = await generator.generate_and_persist(creator.id, old.niche_id)

            # 5. Did the evidence strengthen?
            stage = "decision"
            old_opp = await self._session.get(OpportunityScore, old.opportunity_score_id)
            new_opp = await self._session.get(OpportunityScore, new.opportunity_score_id)
            assert new_opp is not None
            new_evidence = await generator.count_new_evidence(
                creator.id, [old.niche_id], old.generated_at
            )
            decision = decide_resurface(
                self._cfg,
                old_score=old_opp.aggregate_score if old_opp else None,
                old_band=old_opp.confidence_band if old_opp else None,
                new_score=new_opp.aggregate_score,
                new_band=new_opp.confidence_band,
                new_evidence_count=new_evidence,
                content_unchanged=content_fingerprint(new.content)
                == content_fingerprint(old.content),
                always=trigger == "research_more",
            )
            if not decision.resurfaced:
                new.status = DossierStatus.WATCHING
            new.content = {
                **new.content,
                "rescan": {
                    "trigger": trigger,
                    "previous_dossier_id": old.id,
                    "resurfaced": decision.resurfaced,
                    "reason": decision.reason,
                    "score_delta": decision.score_delta,
                    "new_evidence_count": decision.new_evidence_count,
                    "run_id": run.id,
                    "at": datetime.now(UTC).isoformat(),
                },
            }
            await self._session.flush()

            # 6. Creator status follows its active dossiers (R12b).
            await mirror_creator_status(self._session, creator.id)

            stats.ok()
            stats.extra.update(
                {
                    "previous_dossier_id": old.id,
                    "dossier_id": new.id,
                    "resurfaced": decision.resurfaced,
                    "reason": decision.reason,
                    "score_delta": decision.score_delta,
                    "new_evidence_count": decision.new_evidence_count,
                }
            )
            await finish_run(self._session, run, stats)
            return RescanOutcome(
                run_id=run.id,
                previous_dossier_id=old.id,
                dossier_id=new.id,
                status=new.status,
                decision=decision,
            )
        except Exception as exc:
            logger.exception("Rescan of dossier %s failed at stage %r", dossier_id, stage)
            # The orchestrator may have rolled the shared session back (a DB
            # error mid-stage expires every object). Do the bookkeeping on
            # re-fetched rows and never let it mask the original exception.
            try:
                # A DB error in a post-orchestrator stage (dossier, decision,
                # ideation) leaves the transaction poisoned with nobody having
                # rolled back; clear it so the failed run can be recorded.
                if not self._session.is_active:
                    await self._session.rollback()
                run_row = await self._session.get(ResearchRun, run_id)
                if run_row is not None and run_row.status == "running":
                    await fail_run(self._session, run_row, RescanError(f"{stage}: {exc}"))
                await self._restore_if_in_progress(dossier_id)
            except Exception:
                logger.exception(
                    "Could not record the failed rescan of dossier %s (session unusable)",
                    dossier_id,
                )
            raise

    async def _restore_if_in_progress(self, dossier_id: str) -> None:
        """Never leave a Research More dossier stuck in progress."""
        old = await self._session.get(Dossier, dossier_id)
        if (
            old is not None
            and old.superseded_at is None
            and old.status == DossierStatus.RESEARCH_MORE_IN_PROGRESS
        ):
            old.status = DossierStatus.PENDING_REVIEW
            await self._session.flush()
            # The creator was parked at WATCHING for the re-research; with
            # the dossier back in review it must follow (WATCHING →
            # HUMAN_REVIEW is legal).
            await mirror_creator_status(self._session, old.creator_id)


# ── Production wiring ─────────────────────────────────────────────────


def build_watch_rescanner(
    session: AsyncSession,
    provider: Any,
    embedder_factory: Callable[[], Any],
    *,
    scoring_rules_path: str,
    niche_rules_path: str,
    ideation_rules_path: str,
    config: WatchRescanConfig | None = None,
) -> WatchRescanner:
    """Real collaborators: T3's drill engine, the creator orchestrator, T5's
    ideation generator. Imported here (not at module top) so the worker's
    protocols stay import-light for the scheduler and tests."""
    from corp.workers.intelligence.niche_discovery import RecursiveNicheDiscovery
    from corp.workers.intelligence.product_ideation import ProductIdeationGenerator
    from corp.workers.orchestrator import ResearchOrchestrator

    cfg = config or WatchRescanConfig.from_rules(niche_rules_path)
    return WatchRescanner(
        session,
        driller=RecursiveNicheDiscovery(session, provider, niche_rules_path),
        researcher=ResearchOrchestrator(session, provider, embedder_factory),
        ideator=ProductIdeationGenerator(provider, session, ideation_rules_path),
        scoring_rules_path=scoring_rules_path,
        config=cfg,
    )
