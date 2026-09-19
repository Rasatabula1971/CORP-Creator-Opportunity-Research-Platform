"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from corp.api.auth import require_api_key
from corp.api.errors import register_error_handlers
from corp.api.routes import router
from corp.api.routes_ops import health
from corp.api.routes_ops import router as ops_router
from corp.config import settings
from corp.database import async_session
from corp.workers.scheduler.registry_rescan import RegistryRescanScheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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
        if scheduler is not None:
            await scheduler.stop()
            logger.info("Registry re-scan scheduler stopped")


def create_app() -> FastAPI:
    # When an API key is configured, the auto-generated docs/schema routes
    # must be protected too — they aren't covered by the router-level
    # `dependencies=protected` below, since FastAPI serves them directly off
    # the app instance and would otherwise leak every route/param/model.
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
        allow_methods=["*"],
        allow_headers=["*"],
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
