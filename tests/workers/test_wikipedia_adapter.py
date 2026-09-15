"""Tests for the Wikipedia adapter — all HTTP calls mocked."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from corp.workers.adapters.wikipedia import WikipediaAdapter


def _mock_resp(data: dict, status: int = 200) -> MagicMock:
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


SEARCH_RESPONSE = {
    "query": {
        "search": [
            {"title": "Python (programming language)"},
            {"title": "CPython"},
        ]
    }
}

EXTRACT_RESPONSE = {
    "query": {
        "pages": {
            "123": {
                "extract": "Python is a high-level programming language."
            }
        }
    }
}

PAGEVIEWS_RESPONSE = {
    "items": [
        {"timestamp": "2026091400", "views": 5000},
        {"timestamp": "2026091500", "views": 4800},
    ]
}


# ── Adapter properties ──────────────────────────────────────────────


def test_adapter_properties():
    adapter = WikipediaAdapter()
    assert adapter.platform == "wikipedia"
    assert adapter.family.value == "niche"
    assert adapter.access_method.value == "official"
    assert adapter.compliance_status.value == "compliant"


# ── Article collection ───────────────────────────────────────────────


async def test_collect_article(mock_client):
    adapter = WikipediaAdapter(client=mock_client)

    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        url_str = str(url)
        if "pageviews" in url_str or "metrics" in url_str:
            return _mock_resp(PAGEVIEWS_RESPONSE)
        return _mock_resp(EXTRACT_RESPONSE)

    mock_client.get = mock_get

    results = await adapter.collect("article:Python_(programming_language)")

    assert len(results) == 1
    item = results[0]
    assert item.content_type == "pageview_trend"
    assert item.source_platform == "wikipedia"
    assert "Python" in item.text
    assert item.metadata["total_views"] == 9800
    assert item.metadata["avg_daily_views"] == 4900.0
    assert "Python_(programming_language)" in item.external_id


# ── Search and collect ───────────────────────────────────────────────


async def test_search_and_collect(mock_client):
    adapter = WikipediaAdapter(max_articles=2, client=mock_client)

    async def mock_get(url, **kwargs):
        url_str = str(url)
        params = kwargs.get("params", {})
        if params.get("list") == "search":
            return _mock_resp(SEARCH_RESPONSE)
        if "pageviews" in url_str or "metrics" in url_str:
            return _mock_resp(PAGEVIEWS_RESPONSE)
        return _mock_resp(EXTRACT_RESPONSE)

    mock_client.get = mock_get

    results = await adapter.collect("python programming")

    assert len(results) == 2
    assert all(r.content_type == "pageview_trend" for r in results)


# ── Empty search results ─────────────────────────────────────────────


async def test_empty_search(mock_client):
    adapter = WikipediaAdapter(client=mock_client)
    mock_client.get = AsyncMock(
        return_value=_mock_resp({"query": {"search": []}})
    )

    results = await adapter.collect("xyznonexistent")
    assert results == []


# ── Max articles cap ─────────────────────────────────────────────────


async def test_max_articles_respected(mock_client):
    big_search = {
        "query": {
            "search": [{"title": f"Article{i}"} for i in range(20)]
        }
    }
    adapter = WikipediaAdapter(max_articles=3, client=mock_client)

    async def mock_get(url, **kwargs):
        params = kwargs.get("params", {})
        if params.get("list") == "search":
            return _mock_resp(big_search)
        if "pageviews" in str(url) or "metrics" in str(url):
            return _mock_resp(PAGEVIEWS_RESPONSE)
        return _mock_resp(EXTRACT_RESPONSE)

    mock_client.get = mock_get

    results = await adapter.collect("many articles")
    assert len(results) <= 3


# ── Handles pageview API failure gracefully ──────────────────────────


async def test_pageview_failure_graceful(mock_client):
    adapter = WikipediaAdapter(client=mock_client)

    call_idx = 0

    async def mock_get(url, **kwargs):
        nonlocal call_idx
        call_idx += 1
        url_str = str(url)
        if "pageviews" in url_str or "metrics" in url_str:
            raise httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
        return _mock_resp(EXTRACT_RESPONSE)

    mock_client.get = mock_get

    results = await adapter.collect("article:Test_Article")
    assert len(results) == 1
    assert results[0].metadata["total_views"] == 0


# ── URL construction ─────────────────────────────────────────────────


async def test_url_contains_article_title(mock_client):
    adapter = WikipediaAdapter(client=mock_client)

    async def mock_get(url, **kwargs):
        if "pageviews" in str(url) or "metrics" in str(url):
            return _mock_resp(PAGEVIEWS_RESPONSE)
        return _mock_resp(EXTRACT_RESPONSE)

    mock_client.get = mock_get

    results = await adapter.collect("article:Machine_learning")
    assert len(results) == 1
    assert "Machine_learning" in results[0].url


# ── Request counting ─────────────────────────────────────────────────


async def test_request_count(mock_client):
    adapter = WikipediaAdapter(client=mock_client)

    async def mock_get(url, **kwargs):
        if "pageviews" in str(url) or "metrics" in str(url):
            return _mock_resp(PAGEVIEWS_RESPONSE)
        return _mock_resp(EXTRACT_RESPONSE)

    mock_client.get = mock_get

    await adapter.collect("article:Test")
    assert adapter.request_count >= 1


# ── Close ────────────────────────────────────────────────────────────


async def test_close(mock_client):
    adapter = WikipediaAdapter(client=mock_client)
    await adapter.close()
    mock_client.aclose.assert_called_once()
