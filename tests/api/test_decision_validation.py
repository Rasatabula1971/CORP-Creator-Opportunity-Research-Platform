"""No-DB tests: create_decision under the URL-scoped contract.

DecisionCreate carries no creator_id or gate field — the URL alone scopes the
decision — so the old body-vs-URL mismatch checks no longer exist. What's left
to validate without a DB: unknown creator → 404, bad decision value → 422.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from corp.api.errors import register_error_handlers
from corp.api.routes import router
from corp.database import get_session

try:
    from fastapi.testclient import TestClient
    _HAVE_TESTCLIENT = True
except Exception:  # pragma: no cover
    _HAVE_TESTCLIENT = False

pytestmark = pytest.mark.skipif(
    not _HAVE_TESTCLIENT, reason="fastapi TestClient unavailable"
)


def _client(session: MagicMock | None = None) -> "TestClient":
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    async def _fake_session():
        yield session if session is not None else MagicMock()

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app, raise_server_exceptions=False)


def test_unknown_creator_is_404():
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    client = _client(session)
    resp = client.post(
        "/creators/ghost/decisions",
        json={"decision": "approve"},
    )
    assert resp.status_code == 404
    assert "Creator not found" in resp.json()["detail"]


def test_invalid_decision_value_is_422():
    # Pydantic rejects the enum before any DB access.
    client = _client()
    resp = client.post(
        "/creators/abc/decisions",
        json={"decision": "maybe"},
    )
    assert resp.status_code == 422


def test_extra_body_fields_ignored():
    # Old clients may still send creator_id/gate; they're ignored, not a 400.
    # With them ignored, the route proceeds to the creator lookup (404 here).
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    client = _client(session)
    resp = client.post(
        "/creators/abc/decisions",
        json={"creator_id": "different", "gate": "gate_b", "decision": "approve"},
    )
    assert resp.status_code == 404


def test_get_dossier_missing_creator_is_404():
    # session.get -> None means no such creator → 404 (and other errors are no
    # longer masked as "Creator not found").
    from unittest.mock import AsyncMock

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    async def _fake_session():
        s = MagicMock()
        s.get = AsyncMock(return_value=None)
        yield s

    app.dependency_overrides[get_session] = _fake_session
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/creators/ghost/dossier")
    assert resp.status_code == 404
