"""Tests for the search-demand adapter — all HTTP calls mocked."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from corp.workers.adapters.searchdemand import SearchDemandAdapter


def _mock_resp(data: list, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.is_closed = False
    return client


def _autocomplete_response(query: str, suggestions: list[str]) -> list:
    return [query, suggestions]


# ── Adapter properties ──────────────────────────────────────────────


def test_adapter_properties():
    adapter = SearchDemandAdapter()
    assert adapter.platform == "searchdemand"
    assert adapter.family.value == "niche"
    assert adapter.access_method.value == "open"
    assert adapter.compliance_status.value == "compliant"


# ── basic collect ───────────────────────────────────────────────────


async def test_collect_basic(mock_client):
    adapter = SearchDemandAdapter(client=mock_client)
    suggestions = ["best python course", "python tutorial", "python for beginners"]
    mock_client.get = AsyncMock(
        return_value=_mock_resp(_autocomplete_response("python", suggestions))
    )

    results = await adapter.collect("python")

    assert len(results) == 3
    assert results[0].content_type == "question"
    assert results[0].source_platform == "searchdemand"
    assert results[0].text == "best python course"
    assert results[0].metadata["seed_query"] == "python"
    assert results[0].metadata["rank"] == 0
    assert results[1].metadata["rank"] == 1


# ── related: prefix ────────────────────────────────────────────────


async def test_collect_related(mock_client):
    adapter = SearchDemandAdapter(max_suggestions=10, client=mock_client)

    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        params = kwargs.get("params", {})
        q = params.get("q", "")
        return _mock_resp(_autocomplete_response(q, [f"{q} suggestion {i}" for i in range(3)]))

    mock_client.get = mock_get

    results = await adapter.collect("related:python")

    assert call_count > 1
    assert len(results) <= 10
    texts = [r.text for r in results]
    assert len(texts) == len(set(t.lower() for t in texts))


# ── deduplication ──────────────────────────────────────────────────


async def test_deduplication_in_related(mock_client):
    adapter = SearchDemandAdapter(max_suggestions=50, client=mock_client)

    async def mock_get(url, **kwargs):
        return _mock_resp(_autocomplete_response("q", ["same suggestion", "another one"]))

    mock_client.get = mock_get

    results = await adapter.collect("related:python")

    texts_lower = [r.text.lower() for r in results]
    assert len(texts_lower) == len(set(texts_lower))


# ── max_suggestions cap ────────────────────────────────────────────


async def test_max_suggestions_respected(mock_client):
    adapter = SearchDemandAdapter(max_suggestions=5, client=mock_client)

    async def mock_get(url, **kwargs):
        return _mock_resp(
            _autocomplete_response("q", [f"suggestion {i}" for i in range(10)])
        )

    mock_client.get = mock_get

    results = await adapter.collect("related:test")

    assert len(results) <= 5


# ── empty response ─────────────────────────────────────────────────


async def test_empty_response(mock_client):
    adapter = SearchDemandAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(["python", []]))

    results = await adapter.collect("python")
    assert results == []


# ── malformed response ─────────────────────────────────────────────


async def test_malformed_response(mock_client):
    adapter = SearchDemandAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(["just a string"]))

    results = await adapter.collect("python")
    assert results == []


# ── language and country params ────────────────────────────────────


async def test_language_country_params(mock_client):
    adapter = SearchDemandAdapter(
        language="de", country="de", client=mock_client
    )
    mock_client.get = AsyncMock(
        return_value=_mock_resp(_autocomplete_response("test", ["test ergebnis"]))
    )

    results = await adapter.collect("test")

    call_args = mock_client.get.call_args
    params = call_args.kwargs.get("params") or call_args[1].get("params")
    assert params["hl"] == "de"
    assert params["gl"] == "de"
    assert results[0].metadata["language"] == "de"
    assert results[0].metadata["country"] == "de"


# ── request counting ──────────────────────────────────────────────


async def test_request_count(mock_client):
    adapter = SearchDemandAdapter(client=mock_client)
    mock_client.get = AsyncMock(
        return_value=_mock_resp(_autocomplete_response("q", ["a", "b"]))
    )

    await adapter.collect("python")

    assert adapter.request_count == 1


# ── timestamps ─────────────────────────────────────────────────────


async def test_timestamps_present(mock_client):
    adapter = SearchDemandAdapter(client=mock_client)
    mock_client.get = AsyncMock(
        return_value=_mock_resp(_autocomplete_response("q", ["suggestion"]))
    )

    results = await adapter.collect("python")

    assert results[0].timestamp is not None
    assert results[0].timestamp.tzinfo is not None


async def test_implements_search_intent_provider(monkeypatch):
    """CORP1 Stage 4/5, T2: Search Demand is SearchIntentProvider, delegating to collect()."""
    from corp.workers.providers.capabilities import SearchIntentProvider

    adapter = SearchDemandAdapter()
    assert isinstance(adapter, SearchIntentProvider)

    sentinel: list[object] = []
    calls: list[str] = []

    async def fake_collect(identifier: str) -> list[object]:
        calls.append(identifier)
        return sentinel

    monkeypatch.setattr(adapter, "collect", fake_collect)

    assert await adapter.fetch_search_intent("home espresso") is sentinel
    assert calls == ["home espresso"]
