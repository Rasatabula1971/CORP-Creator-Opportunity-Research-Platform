"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from corp.api.auth import require_api_key
from corp.api.errors import register_error_handlers
from corp.api.routes import router
from corp.api.routes_ops import health
from corp.api.routes_ops import router as ops_router
from corp.config import settings
from corp.core.models.workflow import ResearchRun, RunStatus
from corp.database import async_session
from corp.workers.providers.registry import LLMProvider
from corp.workers.scheduler.discovery_scan import DiscoveryHandle, DiscoveryScanScheduler
from corp.workers.scheduler.registry_rescan import (
    RegistryRescanScheduler,
    RescanDeferredError,
    RescannerHandle,
)
from corp.workers.watch_rescan import WatchRescanConfig

logger = logging.getLogger(__name__)


async def _noop_close() -> None:
    return None


class RescanProviders:
    """R12c: the Watch re-scan scheduler's LLM provider, built once and kept
    for the scheduler's lifetime. A per-tick provider would start with an
    empty cooldown table, so "every provider is in cooldown" (design §3.4)
    could never be observed; keeping one lets the pool's state carry
    between ticks. Closed at shutdown."""

    def __init__(self) -> None:
        self._provider: LLMProvider | None = None
        self._unconfigured = False

    async def factory(
        self, session: AsyncSession, cfg: WatchRescanConfig
    ) -> RescannerHandle | None:
        """The scheduler's ``rescanner_factory``: None when no provider is
        configured (re-render only), RescanDeferredError when every pooled
        provider is cooling and the config says to skip such ticks."""
        from corp.api.jobs import _embedder_factory
        from corp.workers.providers.factory import ProviderConfigError, build_provider
        from corp.workers.watch_rescan import build_watch_rescanner

        if self._unconfigured:
            return None
        if self._provider is None:
            try:
                self._provider = build_provider()
            except ProviderConfigError as exc:
                self._unconfigured = True
                logger.warning("Watch re-scan will re-render only (no LLM provider): %s", exc)
                return None
        provider = self._provider
        available = getattr(provider, "available", None)
        if cfg.skip_when_provider_cooling and callable(available) and not available():
            raise RescanDeferredError("every LLM provider is in cooldown")
        try:
            rescanner = build_watch_rescanner(
                session,
                provider,
                _embedder_factory(),
                scoring_rules_path=settings.scoring_rules_path,
                niche_rules_path="rules/niche_discovery_prompt.yaml",
                ideation_rules_path="rules/product_ideation_prompt.yaml",
                config=cfg,
            )
        except Exception:
            await self.aclose()  # do not leak the HTTP client; rebuilt next tick
            raise
        return RescannerHandle(rescanner=rescanner, aclose=_noop_close)

    async def aclose(self) -> None:
        provider, self._provider = self._provider, None
        close = getattr(provider, "close", None) if provider is not None else None
        if callable(close):
            await close()


class DiscoveryProviders:
    """The discovery crawler's LLM + Trends providers, built once and kept
    for the scheduler's lifetime. Same reasoning as RescanProviders: a
    per-tick pool would start with an empty cooldown table, so "every
    provider is cooling" could never be observed. Closed at shutdown."""

    def __init__(self) -> None:
        self._provider: LLMProvider | None = None
        self._trend: object | None = None
        self._trend_unavailable = False
        self._unconfigured = False

    async def factory(self) -> "DiscoveryHandle | None":
        from corp.workers.intelligence.trend_scan import TrendScanConfig
        from corp.workers.providers.capabilities import TrendProvider
        from corp.workers.providers.factory import ProviderConfigError, build_provider
        from corp.workers.scheduler.discovery_scan import (
            DiscoveryDeferredError,
            DiscoveryHandle,
            build_momentum_provider,
        )

        if self._unconfigured:
            return None
        if self._provider is None:
            try:
                self._provider = build_provider()
            except ProviderConfigError as exc:
                self._unconfigured = True
                logger.warning("Discovery crawler disabled (no LLM provider): %s", exc)
                return None
        provider = self._provider

        available = getattr(provider, "available", None)
        if callable(available) and not available():
            raise DiscoveryDeferredError("every LLM provider is in cooldown")

        if self._trend is None and not self._trend_unavailable:
            # Built once and kept: the YouTube chart cache lives on the
            # adapter, so a per-tick rebuild would re-spend the chart's quota
            # on every pass instead of once per cache window.
            try:
                region = TrendScanConfig.from_rules(settings.broad_topics_path).geo
                self._trend = build_momentum_provider(settings, region)
            except Exception as exc:  # noqa: BLE001 — ranking signal only
                logger.info(
                    "Discovery crawler: no momentum source (%s); ranking by rotation", exc
                )
            if self._trend is None:
                self._trend_unavailable = True

        trend = self._trend if isinstance(self._trend, TrendProvider) else None
        # Providers outlive the tick, so releasing one here would defeat the
        # cooldown state this class exists to preserve. aclose() at shutdown.
        return DiscoveryHandle(provider=provider, trend_provider=trend, aclose=_noop_close)

    async def aclose(self) -> None:
        provider, self._provider = self._provider, None
        trend, self._trend = self._trend, None
        self._trend_unavailable = False
        for obj in (provider, trend):
            await _close_quietly(obj)


async def _close_quietly(obj: object | None) -> None:
    if obj is None:
        return
    close = getattr(obj, "close", None)
    if callable(close):
        try:
            await close()
        except Exception:  # noqa: BLE001
            logger.exception("Closing %s failed", type(obj).__name__)


def _discovery_busy() -> bool:
    """Stand the crawler down while the console is already running a
    campaign job, so an unattended pass never races a human-initiated one
    for the same LLM quota. Also stands down for another in-flight
    "discovery" job specifically (campaign-less or not): a manual
    POST /discovery/run and this scheduler's own tick both resolve to the
    same standing autonomous campaign, so letting both run at once can
    create it twice and double whatever quota one pass uses."""
    from corp.api.jobs import JobStatus, registry

    return any(
        j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
        and (j.campaign_id is not None or j.kind == "discovery")
        for j in registry.list(limit=500)
    )


def _job_busy(campaign_id: str | None, creator_id: str) -> bool:
    """A job queued/running for the campaign or the creator: the scheduler
    must not re-research a creator the console is already researching."""
    from corp.api.jobs import registry

    if registry.active_for(creator_id) is not None:
        return True
    return campaign_id is not None and registry.active_for_campaign(campaign_id) is not None


async def _mark_orphaned_runs() -> None:
    """Mark ResearchRun rows stuck in 'running' as 'failed' on startup."""
    now = datetime.now(UTC)
    async with async_session() as session:
        result = await session.execute(
            update(ResearchRun)
            .where(ResearchRun.status == RunStatus.RUNNING.value)
            .values(
                status=RunStatus.FAILED.value,
                error_message="orphaned by process restart",
                completed_at=now,
            )
        )
        count = int(getattr(result, "rowcount", 0) or 0)
        await session.commit()
    if count:
        logger.warning("Marked %d orphaned research runs as failed", count)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        await _mark_orphaned_runs()
    except Exception:
        logger.exception("Failed to sweep orphaned research runs")

    scheduler: RegistryRescanScheduler | None = None
    providers = RescanProviders()
    try:
        scheduler = RegistryRescanScheduler(
            async_session,
            settings.scoring_rules_path,
            rescanner_factory=providers.factory,
            is_busy=_job_busy,
        )
        scheduler.start()
        logger.info("Registry re-scan scheduler started")
    except Exception:
        logger.exception(
            "Registry re-scan scheduler failed to start — API continues without auto-rescan",
        )
    discovery: DiscoveryScanScheduler | None = None
    discovery_providers = DiscoveryProviders()
    if settings.discovery_enabled:
        try:
            discovery = DiscoveryScanScheduler(
                async_session,
                discovery_providers.factory,
                interval_seconds=settings.discovery_interval_seconds,
                topics_per_pass=settings.discovery_topics_per_pass,
                qualification_rules_path=settings.niche_qualification_rules_path,
                broad_topics_path=settings.broad_topics_path,
                is_busy=_discovery_busy,
            )
            discovery.start()
            logger.info(
                "Autonomous discovery crawler started (every %ds)",
                settings.discovery_interval_seconds,
            )
        except Exception:
            logger.exception(
                "Discovery crawler failed to start — API continues without it",
            )
    else:
        logger.info(
            "Autonomous discovery crawler is off "
            "(set DISCOVERY_ENABLED=true; POST /discovery/run runs one pass by hand)",
        )

    try:
        yield
    finally:
        from corp.api.jobs import registry

        stopped = registry.mark_running_as_failed()
        if stopped:
            logger.warning("Marked %d in-flight jobs as failed at shutdown", stopped)
        if scheduler is not None:
            await scheduler.stop()
            logger.info("Registry re-scan scheduler stopped")
        if discovery is not None:
            await discovery.stop()
            logger.info("Discovery crawler stopped")
        try:
            await discovery_providers.aclose()
        except Exception:
            logger.exception("Closing the discovery providers failed")
        try:
            await providers.aclose()
        except Exception:
            logger.exception("Closing the re-scan LLM provider failed")


def create_app() -> FastAPI:
    if not settings.api_key:
        if settings.app_env != "development":
            raise RuntimeError(
                "API_KEY must be set in non-development environments. "
                "Set API_KEY in .env or as an environment variable.",
            )
        logger.warning("API_KEY is not set — all endpoints are unauthenticated")

    protect_docs = bool(settings.api_key)
    app = FastAPI(
        title="CORP",
        description="Creator Opportunity Research Platform",
        lifespan=lifespan,
        docs_url=None if protect_docs else "/docs",
        redoc_url=None if protect_docs else "/redoc",
        openapi_url=None if protect_docs else "/openapi.json",
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Api-Key"],
        expose_headers=["X-Total-Count"],
    )
    register_error_handlers(app)

    # /health is open; everything else requires the API key when one is configured.
    app.add_api_route("/health", health, methods=["GET"], include_in_schema=False)
    protected = [Depends(require_api_key)]
    app.include_router(router, dependencies=protected)
    app.include_router(ops_router, dependencies=protected)
    return app


app = create_app()
