"""No-DB tests for the API exception handlers."""

import pytest
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError

from corp.api.errors import register_error_handlers

try:
    from fastapi.testclient import TestClient
    _HAVE_TESTCLIENT = True
except Exception:  # pragma: no cover - starlette test deps missing
    _HAVE_TESTCLIENT = False

pytestmark = pytest.mark.skipif(
    not _HAVE_TESTCLIENT, reason="fastapi TestClient unavailable"
)


def _app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom-integrity")
    async def boom_integrity():
        # Mimic a unique-constraint violation surfacing from a commit.
        raise IntegrityError("INSERT ...", params={}, orig=Exception("duplicate key"))

    @app.get("/boom-unhandled")
    async def boom_unhandled():
        raise RuntimeError("something else")

    return app


def test_integrity_error_maps_to_409():
    client = TestClient(_app(), raise_server_exceptions=False)
    resp = client.get("/boom-integrity")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "conflict"
    # The raw DB detail must not leak to the caller.
    assert "duplicate key" not in body["detail"]


def test_other_errors_still_500():
    client = TestClient(_app(), raise_server_exceptions=False)
    resp = client.get("/boom-unhandled")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
