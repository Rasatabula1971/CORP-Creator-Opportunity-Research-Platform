"""Tests for /providers/health — the endpoint that reports the active LLM
provider and, for FAIR, runs a live end-to-end probe.

No database is touched — the endpoint calls into ``build_provider`` and, for
FAIR, ``FairProvider.ping()``, both of which we stub. The tests verify the
JSON shape and the routing between the three cases the endpoint distinguishes
(FAIR, non-FAIR, no usable provider).
"""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from corp.api import routes_ops as ops
from corp.api.app import create_app
from corp.workers.providers.factory import ProviderConfigError
from corp.workers.providers.fair import FairProvider, PingResult


@pytest.fixture
def client():
    app = create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class _FakeFair(FairProvider):
    """FairProvider whose router/close/ping are fixed answers, so no real
    FAIR call is needed. It IS a FairProvider so isinstance() still routes
    the endpoint through the FAIR branch."""

    def __init__(self, ping_result: PingResult, member_names: list[str]):
        # Skip real __init__: the router isn't touched by the endpoint.
        self._ping = ping_result
        self._members = member_names
        self._closed = False
        self._last_model = "gemini-3.6-flash"
        self._used = set()

    @property
    def model_name(self) -> str:
        return self._last_model

    def member_names(self) -> list[str]:
        return list(self._members)

    async def ping(self) -> PingResult:
        return self._ping

    async def close(self) -> None:
        self._closed = True


async def test_fair_provider_returns_full_probe(client, monkeypatch):
    ping = PingResult(
        ok=True,
        provider_count=2,
        provider_ids=["google_gemini_api", "groq"],
        solve_status="ACCEPTED",
        solve_provider="groq",
        solve_model="openai/gpt-oss-20b",
        detail="solve accepted",
    )
    fake = _FakeFair(ping, member_names=["fair-router", "gemini-3.6-flash", "groq/openai/gpt-oss-20b"])
    monkeypatch.setattr(ops, "build_provider", lambda: fake)

    resp = await client.get("/providers/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "gemini-3.6-flash"
    assert body["kind"] == "_FakeFair"  # isinstance(FairProvider) still true
    assert body["members"] == ["fair-router", "gemini-3.6-flash", "groq/openai/gpt-oss-20b"]
    assert body["fair"] == {
        "ok": True,
        "provider_count": 2,
        "provider_ids": ["google_gemini_api", "groq"],
        "solve_status": "ACCEPTED",
        "solve_provider": "groq",
        "solve_model": "openai/gpt-oss-20b",
        "detail": "solve accepted",
    }
    # The endpoint releases the client so a real router doesn't leak.
    assert fake._closed is True


async def test_fair_provider_reports_ping_failure_with_200(client, monkeypatch):
    """A probe failure is a diagnostic, not an outage — the endpoint itself
    still returns 200, and the fair block reports ok=False with the reason."""
    ping = PingResult(
        ok=False,
        provider_count=0,
        detail="no providers registered — set GEMINI_API_KEY and/or GROQ_API_KEY",
    )
    fake = _FakeFair(ping, member_names=["fair-router"])
    monkeypatch.setattr(ops, "build_provider", lambda: fake)

    resp = await client.get("/providers/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fair"]["ok"] is False
    assert "no providers registered" in body["fair"]["detail"]


async def test_non_fair_provider_omits_fair_key(client, monkeypatch):
    """A bare Gemini/Groq or a PooledProvider isn't a FairProvider — no
    ping is run, no ``fair`` key appears, but the base fields still do."""

    class _Bare:
        model_name = "gemini-3.6-flash"

    monkeypatch.setattr(ops, "build_provider", lambda: _Bare())

    resp = await client.get("/providers/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "gemini-3.6-flash"
    assert body["kind"] == "_Bare"
    assert "fair" not in body
    assert "members" not in body  # bare providers don't expose member_names()


async def test_non_fair_pool_still_lists_members(client, monkeypatch):
    """PooledProvider isn't FAIR, but it does have member_names — verify
    that member list surfaces even without the FAIR probe."""

    class _Pool:
        model_name = "gemini-3.6-flash"

        def member_names(self):
            return ["gemini-3.6-flash", "groq/openai/gpt-oss-20b"]

    monkeypatch.setattr(ops, "build_provider", lambda: _Pool())

    resp = await client.get("/providers/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["members"] == ["gemini-3.6-flash", "groq/openai/gpt-oss-20b"]
    assert "fair" not in body


async def test_provider_config_error_is_503(client, monkeypatch):
    def raise_it():
        raise ProviderConfigError("No LLM provider configured: set GEMINI_API_KEY ...")

    monkeypatch.setattr(ops, "build_provider", raise_it)

    resp = await client.get("/providers/health")
    assert resp.status_code == 503
    assert "No LLM provider configured" in resp.json()["detail"]


async def test_unexpected_construction_error_returns_200_with_error_block(client, monkeypatch):
    """A diagnostic endpoint must never 500 for the very thing it exists to
    diagnose. Non-ProviderConfigError construction failures (a FAIR version
    mismatch, an incompatible kwarg, a bad env file) surface as data."""

    def raise_it():
        raise TypeError("FAIR.__init__() got an unexpected keyword argument 'env_file'")

    monkeypatch.setattr(ops, "build_provider", raise_it)

    resp = await client.get("/providers/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] is None
    assert body["kind"] is None
    assert body["error"]["code"] == "construction_failed"
    assert "TypeError" in body["error"]["detail"]
    assert "env_file" in body["error"]["detail"]


async def test_close_runs_even_when_ping_raises(monkeypatch):
    """A ping() that raises must still release the client — otherwise a bad
    router leaks resources on every probe. Calls the endpoint function
    directly so the assertion is on the finally block, not on FastAPI's
    error-handler chain."""

    class _Explodes(_FakeFair):
        async def ping(self):
            raise RuntimeError("router blew up")

    fake = _Explodes(
        PingResult(ok=False, provider_count=0),  # unused
        member_names=["fair-router"],
    )
    monkeypatch.setattr(ops, "build_provider", lambda: fake)

    with pytest.raises(RuntimeError, match="router blew up"):
        await ops.provider_health()
    assert fake._closed is True
