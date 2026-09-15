"""In-process background jobs for long-running pipelines.

The console needs to start a research run and poll it. Jobs run on the API
process's event loop via FastAPI BackgroundTasks, each with its own database
session, and report through an in-memory registry.

Limits (deliberate for v1): the registry lives in one process, so it is not
shared across workers and does not survive a restart. ResearchRun rows are
the durable record; a job is only the handle while work is in flight.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from corp.config import settings

logger = logging.getLogger(__name__)

PIPELINES = ("research", "collect", "intelligence", "cluster", "intent", "scoring")


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobResponse(BaseModel):
    id: str
    kind: str
    creator_id: str | None
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] | None = None


class JobRegistry:
    def __init__(self, max_jobs: int = 500) -> None:
        self._jobs: dict[str, JobResponse] = {}
        self._max = max_jobs
        self._lock = asyncio.Lock()

    def create(self, kind: str, creator_id: str | None) -> JobResponse:
        job = JobResponse(
            id=uuid.uuid4().hex,
            kind=kind,
            creator_id=creator_id,
            status=JobStatus.QUEUED,
            created_at=datetime.now(UTC),
        )
        self._jobs[job.id] = job
        if len(self._jobs) > self._max:
            oldest = sorted(self._jobs.values(), key=lambda j: j.created_at)
            for stale in oldest[: len(self._jobs) - self._max]:
                if stale.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    self._jobs.pop(stale.id, None)
        return job

    def get(self, job_id: str) -> JobResponse | None:
        return self._jobs.get(job_id)

    def list(self, creator_id: str | None = None, limit: int = 50) -> list[JobResponse]:
        jobs = [j for j in self._jobs.values() if creator_id is None or j.creator_id == creator_id]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]

    def active_for(self, creator_id: str) -> JobResponse | None:
        for job in self._jobs.values():
            if job.creator_id == creator_id and job.status in (
                JobStatus.QUEUED,
                JobStatus.RUNNING,
            ):
                return job
        return None

    async def execute(
        self, job: JobResponse, work: Callable[[], Awaitable[dict[str, Any]]]
    ) -> None:
        """Run ``work`` and record its outcome on ``job``. Never raises."""
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        try:
            job.result = await work()
            job.status = JobStatus.COMPLETED
        except Exception as exc:  # the job is the error boundary
            logger.exception("Job %s (%s) failed", job.id, job.kind)
            job.status = JobStatus.FAILED
            job.error = str(exc)[:2000]
        finally:
            job.finished_at = datetime.now(UTC)


registry = JobRegistry()


# ── Work functions ───────────────────────────────────────────────────


async def _close(obj: object) -> None:
    close = getattr(obj, "close", None)
    if close is not None:
        await close()


def _embedder_factory():
    from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder

    return lambda: SentenceTransformerEmbedder(settings.embedding_model)


async def run_research(creator_id: str, skip_collect: bool = False) -> dict[str, Any]:
    from corp.database import async_session
    from corp.workers.orchestrator import ResearchOrchestrator
    from corp.workers.providers.factory import build_provider

    provider = build_provider()
    try:
        async with async_session() as session:
            report = await ResearchOrchestrator(session, provider, _embedder_factory()).run(
                creator_id, skip_collect=skip_collect
            )
        return {
            "final_status": report.final_status,
            "runs": [
                {
                    "pipeline": (r.config_snapshot or {}).get("pipeline"),
                    "run_id": r.id,
                    "status": r.status,
                }
                for r in report.runs
            ],
        }
    finally:
        await _close(provider)


async def run_pipeline(
    kind: str,
    creator_id: str,
    platform: str | None = None,
    identifier: str | None = None,
) -> dict[str, Any]:
    """Run one stage. ``collect`` needs platform + identifier."""
    from corp.database import async_session

    if kind == "collect":
        from corp.workers.acquisition.collector import AcquisitionCollector
        from corp.workers.adapters.registry import build_adapter

        if not platform or not identifier:
            raise ValueError("collect requires platform and identifier")
        adapter = build_adapter(platform)
        try:
            async with async_session() as session:
                run = await AcquisitionCollector(adapter, session).collect_creator_data(
                    identifier, creator_id
                )
                await session.commit()
        finally:
            await _close(adapter)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "cluster":
        from corp.workers.intelligence.cluster_pipeline import ClusterPipeline

        async with async_session() as session:
            run = await ClusterPipeline(_embedder_factory()(), session).run(creator_id)
            await session.commit()
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "scoring":
        from corp.workers.intelligence.scoring_pipeline import ScoringPipeline

        async with async_session() as session:
            run = await ScoringPipeline(session, settings.scoring_rules_path).run(creator_id)
            await session.commit()
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind in ("intelligence", "intent"):
        from corp.workers.intelligence.intent_pipeline import IntentPipeline
        from corp.workers.intelligence.pipeline import IntelligencePipeline
        from corp.workers.providers.factory import build_provider

        provider = build_provider()
        try:
            async with async_session() as session:
                if kind == "intelligence":
                    run = await IntelligencePipeline(provider, session).run(creator_id)
                else:
                    run = await IntentPipeline(
                        provider, session, rules_path=settings.intent_rules_path
                    ).run(creator_id)
                await session.commit()
        finally:
            await _close(provider)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    raise ValueError(f"Unknown pipeline {kind!r}; known: {', '.join(PIPELINES)}")
