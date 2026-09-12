"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from corp.api.routes import router
from corp.config import settings


def _get_cors_origins() -> list[str]:
    if settings.cors_origins:
        return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if settings.app_env == "development":
        return ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000"]
    return []


def create_app() -> FastAPI:
    app = FastAPI(title="CORP", description="Creator Opportunity Research Platform")
    origins = _get_cors_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(router)
    return app


app = create_app()
