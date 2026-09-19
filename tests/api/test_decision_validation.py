"""No-DB tests: create_decision rejects a body inconsistent with the URL/endpoint."""

from unittest.mock import MagicMock

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


def _client() -> "TestClient":
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    async def _fake_session():
        # Validation runs before any DB access, so this is never used on the
        # 400 paths under test.
        yield MagicMock()

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app, raise_server_exceptions=False)


def test_body_creator_id_mismatch_rejected():
    client = _client()
    resp = client.post(
        "/creators/abc/decisions",
        json={"creator_id": "different", "gate": "gate_a", "decision": "approve"},
    )
    assert resp.status_code == 400
    assert "creator_id" in resp.json()["detail"]


def test_non_gate_a_rejected():
    client = _client()
    resp = client.post(
        "/creators/abc/decisions",
        json={"creator_id": "abc", "gate": "gate_b", "decision": "approve"},
    )
    assert resp.status_code == 400
    assert "Gate A" in resp.json()["detail"]


def test_invalid_transition_returns_dedicated_error_code():
    """record_gate_a_decision's InvalidTransitionError must propagate to the
    app-level handler (409, code="invalid_transition"), not get swallowed
    into a generic HTTPException(409) with code="conflict"."""
    from unittest.mock import AsyncMock, patch

    from corp.core.state.machine import InvalidTransitionError

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    async def _fake_session():
        s = MagicMock()
        s.get = AsyncMock(return_value=MagicMock())
        yield s

    app.dependency_overrides[get_session] = _fake_session
    client = TestClient(app, raise_server_exceptions=False)

    with patch(
        "corp.api.routes.record_gate_a_decision",
        AsyncMock(side_effect=InvalidTransitionError("creator already decided")),
    ):
        resp = client.post(
            "/creators/abc/decisions",
            json={"creator_id": "abc", "gate": "gate_a", "decision": "approve"},
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invalid_transition"


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
