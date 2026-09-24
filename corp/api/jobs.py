"""In-process background jobs for long-running pipelines.

The console needs to start a research run and poll it. Jobs run on the API
process's event loop via FastAPI BackgroundTasks, each with its own database
session, and report through an in-memory registry.

Limits (deliberate for v1): the registry lives in one process, so it is not
shared across workers and does not survive a restart. ResearchRun rows are
the durable record; a job is only the handle while work is in flight.
"""

import functools
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

    def active_of_kind(self, kind: str) -> JobResponse | None:
        """The in-flight job of a given kind, if any. Campaign-less jobs
        (an autonomous discovery pass attaches to no campaign until it
        picks one) are invisible to active_for_campaign, so this is how
        the status endpoint reports one as running."""
        for job in self._jobs.values():
            if job.kind == kind and job.status in (
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
            job.error = type(exc).__name__
        finally:
            job.finished_at = datetime.now(UTC)

    def mark_running_as_failed(self) -> int:
        """Mark any still-running jobs as failed (called at shutdown)."""
        count = 0
        now = datetime.now(UTC)
        for job in self._jobs.values():
            if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                job.status = JobStatus.FAILED
                job.error = "interrupted by shutdown"
                job.finished_at = now
                count += 1
        return count


registry = JobRegistry()


# ── Work functions ───────────────────────────────────────────────────


async def _close(obj: object) -> None:
    from corp.workers.adapters.base import close_quietly

    await close_quietly(obj)


async def _commit_or_rollback(session: Any) -> None:
    """Persist whatever a crashing pipeline flushed (e.g. a failed ResearchRun).

    If the session is poisoned (a DB error aborted the transaction), commit
    is impossible, so roll back instead — the run record is lost, but the
    original exception propagates cleanly.
    """
    try:
        await session.commit()
    except Exception:
        logger.exception("could not persist failed run; rolling back")
        await session.rollback()


@functools.lru_cache(maxsize=1)
def _embedder_factory() -> "Callable[[], SentenceTransformerEmbedder]":
    from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder

    @functools.lru_cache(maxsize=1)
    def _singleton() -> SentenceTransformerEmbedder:
        return SentenceTransformerEmbedder(settings.embedding_model)

    return _singleton


async def _refresh_micro_niches(creator_id: str | None = None) -> dict[str, int] | None:
    """Queue micro-niche suggestions from freshly researched audience
    clusters. Best-effort: database reads only, and a failure here must
    never fail the research job that just succeeded."""
    from corp.database import async_session
    from corp.workers.intelligence.micro_niches import MicroNicheSeeder

    try:
        async with async_session() as session:
            stats = await MicroNicheSeeder(
                session,
                min_frequency=settings.micro_niche_min_frequency,
                min_followers=settings.micro_niche_min_followers,
                max_followers=settings.micro_niche_max_followers,
            ).suggest(creator_id=creator_id)
            await session.commit()
        return stats.as_dict()
    except Exception:
        logger.exception("Refreshing micro-niche suggestions failed (research is unaffected)")
        return None


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
        result: dict[str, Any] = {
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
    result["micro_niche_suggestions"] = await _refresh_micro_niches(creator_id)
    return result


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
                try:
                    run = await AcquisitionCollector(adapter, session).collect_creator_data(
                        identifier, creator_id
                    )
                    await session.commit()
                except Exception:
                    await _commit_or_rollback(session)
                    raise
        finally:
            await _close(adapter)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "cluster":
        from corp.workers.intelligence.cluster_pipeline import ClusterPipeline

        async with async_session() as session:
            try:
                run = await ClusterPipeline(_embedder_factory()(), session).run(creator_id)
                await session.commit()
            except Exception:
                await _commit_or_rollback(session)
                raise
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "scoring":
        from corp.workers.intelligence.scoring_pipeline import ScoringPipeline

        async with async_session() as session:
            try:
                run = await ScoringPipeline(session, settings.scoring_rules_path).run(creator_id)
                await session.commit()
            except Exception:
                await _commit_or_rollback(session)
                raise
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind in ("intelligence", "intent"):
        from corp.workers.intelligence.intent_pipeline import IntentPipeline
        from corp.workers.intelligence.pipeline import IntelligencePipeline
        from corp.workers.providers.factory import build_provider

        provider = build_provider()
        try:
            async with async_session() as session:
                try:
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
                except Exception:
                    await _commit_or_rollback(session)
                    raise
        finally:
            await _close(provider)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    raise ValueError(f"Unknown pipeline {kind!r}; known: {', '.join(PIPELINES)}")


# ── Campaign pipeline work functions ──────────────────────────────


async def run_discovery_scan(
    topics: list[str] | None = None,
    topics_per_pass: int | None = None,
    campaign_id: str | None = None,
) -> dict[str, Any]:
    """One autonomous discovery pass (CORP1 Step 1, Level 0 onwards).

    With no arguments this is the crawler entry point: the trend scan
    picks the topics. With ``topics`` it is the spec's user-suggested
    alternate entry point, taking the same path through the drill engine
    so a hand-picked niche yields the same evidence and lineage.
    """
    from corp.database import async_session
    from corp.workers.intelligence.trend_scan import TrendScanConfig
    from corp.workers.providers.capabilities import TrendProvider
    from corp.workers.providers.factory import build_provider
    from corp.workers.scheduler.discovery_scan import (
        build_momentum_provider,
        run_discovery_pass,
    )

    provider = build_provider()
    # The momentum signal is optional: a missing or broken source downgrades
    # ranking to rotation rather than failing the pass. User-supplied topics
    # skip the scan entirely, so they need no momentum source at all.
    trend_provider: TrendProvider | None = None
    if not topics:
        try:
            region = TrendScanConfig.from_rules(settings.broad_topics_path).geo
            trend_provider = build_momentum_provider(settings, region)
        except Exception as exc:  # noqa: BLE001 — ranking only
            logger.info("Discovery scan: no momentum source (%s); ranking by rotation", exc)

    try:
        async with async_session() as session:
            try:
                stats = await run_discovery_pass(
                    session,
                    provider,
                    trend_provider=trend_provider,
                    topics_per_pass=topics_per_pass,
                    campaign_id=campaign_id,
                    topics=topics,
                    broad_topics_path=settings.broad_topics_path,
                )
                await session.commit()
            except Exception:
                await _commit_or_rollback(session)
                raise
    finally:
        await _close(provider)
        if trend_provider is not None:
            await _close(trend_provider)
    return stats.as_dict()


async def run_campaign_pipeline(
    kind: str,
    campaign_id: str,
    source: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Run a campaign-level pipeline stage as a background job."""
    from corp.database import async_session

    if kind == "discover":
        from corp.workers.intelligence.niche_discovery import RecursiveNicheDiscovery
        from corp.workers.providers.factory import build_provider

        if not query:
            raise ValueError("discover requires query (the broad topic)")
        provider = build_provider()
        try:
            async with async_session() as session:
                try:
                    discovery = RecursiveNicheDiscovery(
                        session, provider, "rules/niche_discovery_prompt.yaml"
                    )
                    run = await discovery.discover(campaign_id, query)
                    await session.commit()
                except Exception:
                    await _commit_or_rollback(session)
                    raise
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
                try:
                    gen = NicheCandidateGenerator(
                        SentenceTransformerEmbedder(settings.embedding_model),
                        provider,
                        session,
                    )
                    run = await gen.generate(campaign_id)
                    await session.commit()
                except Exception:
                    await _commit_or_rollback(session)
                    raise
        finally:
            await _close(provider)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "canonicalize":
        from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder
        from corp.workers.intelligence.niche_canonicalization import (
            CanonConfig,
            NicheCanonicalizer,
        )
        from corp.workers.intelligence.niche_discovery import DiscoveryConfig

        recheck_days = DiscoveryConfig.from_rules(
            "rules/niche_discovery_prompt.yaml"
        ).recheck_days
        async with async_session() as session:
            try:
                canon = NicheCanonicalizer(
                    SentenceTransformerEmbedder(settings.embedding_model),
                    session,
                    CanonConfig(recheck_days=recheck_days),
                )
                run = await canon.canonicalize(campaign_id)
                await session.commit()
            except Exception:
                await _commit_or_rollback(session)
                raise
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "verify":
        from corp.workers.intelligence.niche_verification import NicheVerifier

        async with async_session() as session:
            try:
                run = await NicheVerifier(session).verify(campaign_id)
                await session.commit()
            except Exception:
                await _commit_or_rollback(session)
                raise
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
                try:
                    run = await EcosystemEstimator(adapter, session, enricher=enricher).estimate(
                        campaign_id,
                    )
                    await session.commit()
                except Exception:
                    await _commit_or_rollback(session)
                    raise
        finally:
            await _close(adapter)
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "qualify":
        from corp.workers.intelligence.niche_qualification import NicheQualifier

        async with async_session() as session:
            try:
                run = await NicheQualifier(
                    session, settings.niche_qualification_rules_path,
                ).qualify_campaign(campaign_id)
                await session.commit()
            except Exception:
                await _commit_or_rollback(session)
                raise
        return {"run_id": run.id, "status": run.status, "stats": run.stats}

    if kind == "select":
        from corp.workers.intelligence.niche_selection import NicheSelector

        async with async_session() as session:
            try:
                run = await NicheSelector(session).select(campaign_id)
                await session.commit()
            except Exception:
                await _commit_or_rollback(session)
                raise
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
                try:
                    run = await CreatorOnboarder(
                        adapter, session, enricher=enricher
                    ).onboard(campaign_id)
                    await session.commit()
                except Exception:
                    await _commit_or_rollback(session)
                    raise
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
                try:
                    orchestrator = ResearchOrchestrator(session, provider, _embedder_factory())
                    batch = CampaignResearchBatch(orchestrator, session)
                    run = await batch.run_campaign(campaign_id)
                    await session.commit()
                except Exception:
                    await _commit_or_rollback(session)
                    raise
        finally:
            await _close(provider)
        return {
            "run_id": run.id,
            "status": run.status,
            "stats": run.stats,
            "micro_niche_suggestions": await _refresh_micro_niches(),
        }

    raise ValueError(f"Unknown campaign pipeline {kind!r}; known: {', '.join(CAMPAIGN_PIPELINES)}")
