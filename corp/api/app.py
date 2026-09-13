"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from corp.api.dashboard import dashboard_router
from corp.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="CORP", description="Creator Opportunity Research Platform")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(dashboard_router)
    return app


app = create_app()
