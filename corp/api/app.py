"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from corp.api.auth import require_api_key
from corp.api.errors import register_error_handlers
from corp.api.routes import router
from corp.api.routes_ops import health
from corp.api.routes_ops import router as ops_router
from corp.config import settings
from corp.core.models.workflow import ResearchRun, RunStatus
from corp.database import async_session
from corp.workers.scheduler.registry_rescan import RegistryRescanScheduler

logger = logging.getLogger(__name__)


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
    try:
        scheduler = RegistryRescanScheduler(
            async_session,
            settings.scoring_rules_path,
        )
        scheduler.start()
        logger.info("Registry re-scan scheduler started")
    except Exception:
        logger.exception(
            "Registry re-scan scheduler failed to start — API continues without auto-rescan",
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
