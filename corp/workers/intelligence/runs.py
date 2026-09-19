"""Shared run lifecycle for every pipeline.

* :func:`start_run` / :func:`finish_run` — ResearchRun bookkeeping with
  failure accounting (completed / partial / failed).
* :func:`stage` — moves the creator through the state machine around a
  pipeline stage and restores the previous status when the stage fails.
* :func:`active_clusters_for_creator` / :func:`supersede` — latest-wins reads
  and writes for clusters, signals and scores. Rows are never deleted.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.workflow import ResearchRun, RunScope, RunStatus, RunType
from corp.core.state.transitions import advance, restore

logger = logging.getLogger(__name__)

DEFAULT_MAX_FAILURE_RATE = 0.2


@dataclass
class PipelineStats:
    """Counts one pipeline run keeps while it works. Persisted on the run."""

    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    last_error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def ok(self) -> None:
        self.attempted += 1
        self.succeeded += 1

    def fail(self, exc: BaseException) -> None:
        self.attempted += 1
        self.failed += 1
        self.last_error = str(exc)[:500]

    def skip(self) -> None:
        self.skipped += 1

    @property
    def failure_rate(self) -> float:
        return self.failed / self.attempted if self.attempted else 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["failure_rate"] = round(self.failure_rate, 4)
        return data


def resolve_status(stats: PipelineStats, max_failure_rate: float) -> str:
    """Decide a run's terminal status from its stats."""
    if stats.attempted and stats.failed == stats.attempted:
        return RunStatus.FAILED.value
    if stats.failure_rate > max_failure_rate:
        return RunStatus.PARTIAL.value
    return RunStatus.COMPLETED.value


async def start_run(
    session: AsyncSession,
    *,
    pipeline: str,
    creator_id: str | None,
    config: dict[str, Any] | None = None,
    prompt_versions: dict[str, Any] | None = None,
    model_versions: dict[str, Any] | None = None,
    scope: RunScope | None = None,
    run_type: RunType | None = None,
    campaign_id: str | None = None,
    niche_id: str | None = None,
) -> ResearchRun:
    # run_type / campaign_id / niche_id default to None so every existing
    # creator-pipeline call site keeps its behavior (run_type falls back to
    # the model default, CREATOR_RESEARCH). Only new upstream call sites
    # (niche discovery / verification) pass them.
    run = ResearchRun(
        creator_id=creator_id,
        campaign_id=campaign_id,
        niche_id=niche_id,
        scope=(scope or (RunScope.CREATOR if creator_id else RunScope.CROSS)).value,
        status=RunStatus.RUNNING.value,
        started_at=datetime.now(UTC),
        config_snapshot={"pipeline": pipeline, **(config or {})},
        prompt_versions=prompt_versions or {},
        model_versions=model_versions or {},
    )
    if run_type is not None:
        run.run_type = run_type.value
    session.add(run)
    await session.flush()
    return run


async def finish_run(
    session: AsyncSession,
    run: ResearchRun,
    stats: PipelineStats,
    *,
    max_failure_rate: float = DEFAULT_MAX_FAILURE_RATE,
) -> ResearchRun:
    """Close a run: ``completed`` / ``partial`` / ``failed`` by the failure rate.

    Never raises for a failed run. A run where every unit failed is still
    research memory (§13) — the row must reach the database, and it only does
    if the caller's normal commit runs. Callers and the orchestrator read
    ``run.status``. (Until 2026-09-14 this raised, and the caller's rollback
    erased every fully failed run — see docs/DECISIONS/0009.)
    """
    run.stats = stats.to_dict()
    run.completed_at = datetime.now(UTC)
    run.status = resolve_status(stats, max_failure_rate)
    if run.status == RunStatus.FAILED.value:
        run.error_message = (stats.last_error or "all work units failed")[:2000]
        logger.error("run %s failed: %s", run.id, run.error_message)
    elif run.status == RunStatus.PARTIAL.value:
        run.error_message = (
            f"{stats.failed}/{stats.attempted} units failed "
            f"(max {max_failure_rate:.0%}); last: {stats.last_error}"
        )[:2000]
    await session.flush()
    return run


async def fail_run(session: AsyncSession, run: ResearchRun, exc: BaseException) -> None:
    run.status = RunStatus.FAILED.value
    run.error_message = str(exc)[:2000]
    run.completed_at = datetime.now(UTC)
    await session.flush()


@asynccontextmanager
async def stage(
    session: AsyncSession,
    creator_id: str | None,
    *,
    working: CreatorStatus,
    done: CreatorStatus,
    run: ResearchRun | None = None,
) -> AsyncIterator[Creator | None]:
    """Advance the creator to ``working`` for the block, then ``done`` on success.

    The previous status is restored on an exception, and also when ``run`` is
    given and finishes ``failed`` — a stage that produced nothing must not
    leave the creator looking as if it had. A missing creator or an invalid
    transition never blocks the pipeline; it is logged and skipped.
    """
    creator = await session.get(Creator, creator_id) if creator_id else None
    if creator is None:
        yield None
        return

    previous = creator.status
    moved = await advance(session, creator, working)
    try:
        yield creator
    except BaseException:
        if moved:
            await restore(session, creator, previous)
        raise
    else:
        if not moved:
            return
        if run is not None and run.status == RunStatus.FAILED.value:
            logger.warning(
                "stage %s -> %s produced nothing for creator %s; restoring %s",
                working.value,
                done.value,
                creator.id,
                previous.value,
            )
            await restore(session, creator, previous)
        else:
            await advance(session, creator, done)


def _clusters_for_creator_condition(creator_id: str) -> Any:
    """Clusters tagged with the creator, or whose members' evidence came from their runs."""
    via_membership = (
        select(ProblemClusterMember.cluster_id)
        .join(ProblemObservation, ProblemObservation.id == ProblemClusterMember.observation_id)
        .join(Evidence, Evidence.id == ProblemObservation.evidence_id)
        .join(ResearchRun, ResearchRun.id == Evidence.research_run_id)
        .where(ResearchRun.creator_id == creator_id)
    )
    return or_(
        ProblemCluster.creator_id == creator_id,
        ProblemCluster.id.in_(via_membership),
    )


async def active_clusters_for_creator(
    session: AsyncSession, creator_id: str | None
) -> list[ProblemCluster]:
    stmt = select(ProblemCluster).where(ProblemCluster.superseded_at.is_(None))
    if creator_id:
        stmt = stmt.where(_clusters_for_creator_condition(creator_id))
    result = await session.execute(stmt.order_by(ProblemCluster.created_at))
    return list(result.scalars().all())


async def supersede(session: AsyncSession, model: Any, *conditions: Any) -> int:
    """Mark every active row of ``model`` matching ``conditions`` as superseded."""
    now = datetime.now(UTC)
    result = await session.execute(
        update(model)
        .where(model.superseded_at.is_(None), *conditions)
        .values(superseded_at=now, updated_at=now)
    )
    return int(getattr(result, "rowcount", 0) or 0)

