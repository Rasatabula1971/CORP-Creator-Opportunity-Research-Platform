"""FastAPI application factory."""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from corp.api.auth import require_api_key
from corp.api.errors import register_error_handlers
from corp.api.routes import router
from corp.api.routes_ops import health
from corp.api.routes_ops import router as ops_router
from corp.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title="CORP", description="Creator Opportunity Research Platform")

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
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
