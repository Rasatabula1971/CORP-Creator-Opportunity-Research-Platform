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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder

from pydantic import BaseModel

from corp.config import settings

logger = logging.getLogger(__name__)

PIPELINES = ("research", "collect", "intelligence", "cluster", "intent", "scoring")

CAMPAIGN_PIPELINES = (
    "discover",
    "candidates",
    "canonicalize",
    "verify",
    "estimate-ecosystem",
    "qualify",
    "select",
    "onboard",
    "research-campaign",
)


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobResponse(BaseModel):
    id: str
    kind: str
    creator_id: str | None = None
    campaign_id: str | None = None
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

    def create(
        self,
        kind: str,
        creator_id: str | None = None,
        campaign_id: str | None = None,
    ) -> JobResponse:
        job = JobResponse(
            id=uuid.uuid4().hex,
            kind=kind,
            creator_id=creator_id,
            campaign_id=campaign_id,
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

    def list(
        self,
        creator_id: str | None = None,
        campaign_id: str | None = None,
        limit: int = 50,
    ) -> list[JobResponse]:
        jobs = list(self._jobs.values())
        if creator_id is not None:
            jobs = [j for j in jobs if j.creator_id == creator_id]
        if campaign_id is not None:
            jobs = [j for j in jobs if j.campaign_id == campaign_id]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]

    def active_for(self, creator_id: str) -> JobResponse | None:
        for job in self._jobs.values():
            if job.creator_id == creator_id and job.status in (
                JobStatus.QUEUED,
                JobStatus.RUNNING,
            ):
                return job
        return None

    def active_for_campaign(self, campaign_id: str) -> JobResponse | None:
        for job in self._jobs.values():
            if job.campaign_id == campaign_id and job.status in (
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


def _embedder_factory() -> "Callable[[], SentenceTransformerEmbedder]":
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
                    run = await IntelligencePipeline(
                        provider, session,
                        max_failure_rate=settings.pipeline_max_failure_rate,
                    ).run(creator_id)
                else:
                    run = await IntentPipeline(
                        provider, session, rules_path=settings.intent_rules_path,
                        max_failure_rate=settings.pipeline_max_failure_rate,
                    ).run(creator_id)
                await session.commit()
        finally:
            await _close(provider)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    raise ValueError(f"Unknown pipeline {kind!r}; known: {', '.join(PIPELINES)}")


# ── Campaign pipeline work functions ──────────────────────────────


async def run_campaign_pipeline(
    kind: str,
    campaign_id: str,
    source: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Run a campaign-level pipeline stage as a background job."""
    from corp.database import async_session

    if kind == "discover":
        # CORP1 Stage 5, T4: this stage now runs T3's recursive discovery
        # engine end-to-end (capability fan-out -> LLM synthesis -> recurse
        # to depth 3), which produces STAGED NicheCandidate rows directly.
        # It replaces both the old single-platform NicheDiscoveryCollector
        # and, functionally, the separate "candidates" clustering stage
        # that used to run after it -- "candidates" remains callable below
        # unchanged (other evidence-collection paths may still want it),
        # it is simply no longer part of the default flow this stage feeds.
        # `source` is accepted but unused: T3 fans out across every
        # NICHE-family capability provider automatically, there is no
        # single platform to choose. `query` is the broad topic.
        from corp.workers.intelligence.niche_discovery import RecursiveNicheDiscovery
        from corp.workers.providers.factory import build_provider

        if not query:
            raise ValueError("discover requires query (the broad topic)")
        provider = build_provider()
        try:
            async with async_session() as session:
                discovery = RecursiveNicheDiscovery(
                    session, provider, "rules/niche_discovery_prompt.yaml"
                )
                run = await discovery.discover(campaign_id, query)
                await session.commit()
        finally:
            await _close(provider)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "candidates":
        from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder
        from corp.workers.intelligence.niche_candidates import NicheCandidateGenerator
        from corp.workers.providers.factory import build_provider

        provider = build_provider()
        try:
            async with async_session() as session:
                gen = NicheCandidateGenerator(
                    SentenceTransformerEmbedder(settings.embedding_model),
                    provider,
                    session,
                )
                run = await gen.generate(campaign_id)
                await session.commit()
        finally:
            await _close(provider)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "canonicalize":
        from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder
        from corp.workers.intelligence.niche_canonicalization import NicheCanonicalizer

        async with async_session() as session:
            canon = NicheCanonicalizer(
                SentenceTransformerEmbedder(settings.embedding_model),
                session,
            )
            run = await canon.canonicalize(campaign_id)
            await session.commit()
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "verify":
        from corp.workers.intelligence.niche_verification import NicheVerifier

        async with async_session() as session:
            run = await NicheVerifier(session).verify(campaign_id)
            await session.commit()
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "estimate-ecosystem":
        from corp.workers.adapters.registry import build_search_adapter
        from corp.workers.intelligence.ecosystem_estimator import (
            EcosystemEstimator,
            YouTubeAPIEnricher,
        )

        adapter = build_search_adapter("youtube")
        enricher = (
            YouTubeAPIEnricher(settings.youtube_api_key) if settings.youtube_api_key else None
        )
        try:
            async with async_session() as session:
                run = await EcosystemEstimator(adapter, session, enricher=enricher).estimate(
                    campaign_id,
                )
                await session.commit()
        finally:
            await _close(adapter)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "qualify":
        from corp.workers.intelligence.niche_qualification import NicheQualifier

        async with async_session() as session:
            run = await NicheQualifier(
                session, settings.niche_qualification_rules_path,
            ).qualify_campaign(campaign_id)
            await session.commit()
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "select":
        from corp.workers.intelligence.niche_selection import NicheSelector

        async with async_session() as session:
            run = await NicheSelector(session).select(campaign_id)
            await session.commit()
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "onboard":
        from corp.workers.acquisition.creator_onboarding import CreatorOnboarder
        from corp.workers.adapters.registry import build_search_adapter
        from corp.workers.intelligence.ecosystem_estimator import YouTubeAPIEnricher

        adapter = build_search_adapter("youtube")
        enricher = (
            YouTubeAPIEnricher(settings.youtube_api_key) if settings.youtube_api_key else None
        )
        try:
            async with async_session() as session:
                run = await CreatorOnboarder(
                    adapter, session, enricher=enricher
                ).onboard(campaign_id)
                await session.commit()
        finally:
            await _close(adapter)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "research-campaign":
        from corp.workers.campaign_research import CampaignResearchBatch
        from corp.workers.orchestrator import ResearchOrchestrator
        from corp.workers.providers.factory import build_provider

        provider = build_provider()
        try:
            async with async_session() as session:
                orchestrator = ResearchOrchestrator(session, provider, _embedder_factory())
                batch = CampaignResearchBatch(orchestrator, session)
                run = await batch.run_campaign(campaign_id)
                await session.commit()
        finally:
            await _close(provider)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    raise ValueError(f"Unknown campaign pipeline {kind!r}; known: {', '.join(CAMPAIGN_PIPELINES)}")
