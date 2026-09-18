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


def test_starlette_404_uses_error_handler():
    """A request to an unregistered path triggers Starlette's base HTTPException
    (not FastAPI's subclass). The handler must be registered on the base class
    so these 404s get the standard error body, not Starlette's default HTML."""
    client = TestClient(_app(), raise_server_exceptions=False)
    resp = client.get("/no-such-route")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "detail" in body


def test_starlette_405_uses_error_handler():
    """A POST to a GET-only route triggers a 405 from Starlette's router."""
    app = _app()

    @app.get("/get-only")
    async def get_only():
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/get-only")
    assert resp.status_code == 405
    body = resp.json()
    assert "error" in body
