"""Tests for the Apple App Store adapter — all HTTP calls mocked."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from corp.workers.adapters.appstore import (
    AppStoreAdapter,
    _parse_review_feed,
)


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


REVIEW_FEED = {
    "feed": {
        "entry": [
            {
                "id": {"label": "9999001"},
                "title": {"label": "Great app but missing feature"},
                "content": {"label": "Love the design, but wish it had dark mode."},
                "im:rating": {"label": "3"},
                "author": {"name": {"label": "ReviewerOne"}},
                "im:name": {"label": "CoolApp Pro"},
                "link": {"attributes": {"href": "https://apps.apple.com/review/1"}},
            },
            {
                "id": {"label": "9999002"},
                "title": {"label": "Crashes on startup"},
                "content": {"label": "Every time I open the app it crashes."},
                "im:rating": {"label": "1"},
                "author": {"name": {"label": "ReviewerTwo"}},
                "im:name": {"label": "CoolApp Pro"},
                "link": {"attributes": {"href": "https://apps.apple.com/review/2"}},
            },
            {
                "title": {"label": "App Info"},
                "content": {"label": "CoolApp Pro description"},
            },
        ]
    }
}

SEARCH_RESPONSE = {
    "results": [
        {"trackId": 123456, "trackName": "CoolApp Pro"},
        {"trackId": 789012, "trackName": "CoolApp Lite"},
    ]
}


# ── Adapter properties ──────────────────────────────────────────────


def test_adapter_properties():
    adapter = AppStoreAdapter()
    assert adapter.platform == "appstore"
    assert adapter.family.value == "niche"
    assert adapter.access_method.value == "open"
    assert adapter.compliance_status.value == "compliant"


# ── Feed parsing ─────────────────────────────────────────────────────


def test_parse_review_feed():
    results = _parse_review_feed(REVIEW_FEED, "123456")
    assert len(results) == 2

    r1 = results[0]
    assert r1.content_type == "review"
    assert r1.source_platform == "appstore"
    assert "Great app but missing feature" in r1.text
    assert "dark mode" in r1.text
    assert r1.metadata["star_rating"] == 3
    assert r1.metadata["app_name"] == "CoolApp Pro"
    assert r1.metadata["app_id"] == "123456"
    assert r1.author == "ReviewerOne"
    assert r1.external_id == "as_9999001"
    assert r1.url == "https://apps.apple.com/review/1"

    r2 = results[1]
    assert r2.metadata["star_rating"] == 1
    assert "Crashes on startup" in r2.text


def test_parse_skips_entries_without_rating():
    results = _parse_review_feed(REVIEW_FEED, "123456")
    assert all("star_rating" in r.metadata for r in results)


def test_parse_empty_feed():
    assert _parse_review_feed({"feed": {"entry": []}}, "1") == []
    assert _parse_review_feed({"feed": {}}, "1") == []
    assert _parse_review_feed({}, "1") == []


def test_parse_single_entry_dict():
    feed = {
        "feed": {
            "entry": {
                "id": {"label": "5001"},
                "title": {"label": "Nice"},
                "content": {"label": "Good app"},
                "im:rating": {"label": "5"},
                "author": {"name": {"label": "Solo"}},
                "im:name": {"label": "TestApp"},
            }
        }
    }
    results = _parse_review_feed(feed, "999")
    assert len(results) == 1
    assert results[0].metadata["star_rating"] == 5


# ── collect by ID ────────────────────────────────────────────────────


async def test_collect_by_id(mock_client):
    adapter = AppStoreAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(REVIEW_FEED))

    results = await adapter.collect("id:123456")

    assert len(results) == 2
    assert all(r.metadata["app_id"] == "123456" for r in results)


# ── collect by search ────────────────────────────────────────────────


async def test_collect_by_search(mock_client):
    adapter = AppStoreAdapter(max_apps=2, max_reviews=10, client=mock_client)

    async def mock_get(url, **kwargs):
        url_str = str(url)
        if "search" in url_str:
            return _mock_resp(SEARCH_RESPONSE)
        return _mock_resp(REVIEW_FEED)

    mock_client.get = mock_get

    results = await adapter.collect("search:cool app")
    assert len(results) > 0
    assert all(r.content_type == "review" for r in results)


async def test_collect_bare_keyword(mock_client):
    adapter = AppStoreAdapter(max_apps=1, max_reviews=5, client=mock_client)

    async def mock_get(url, **kwargs):
        url_str = str(url)
        if "search" in url_str:
            return _mock_resp(SEARCH_RESPONSE)
        return _mock_resp(REVIEW_FEED)

    mock_client.get = mock_get

    results = await adapter.collect("productivity")
    assert len(results) > 0


# ── Max reviews cap ──────────────────────────────────────────────────


async def test_max_reviews_respected(mock_client):
    adapter = AppStoreAdapter(max_reviews=1, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(REVIEW_FEED))

    results = await adapter.collect("id:123456")
    assert len(results) == 1


# ── Empty search results ─────────────────────────────────────────────


async def test_empty_search_results(mock_client):
    adapter = AppStoreAdapter(client=mock_client)

    async def mock_get(url, **kwargs):
        url_str = str(url)
        if "search" in url_str:
            return _mock_resp({"results": []})
        return _mock_resp(REVIEW_FEED)

    mock_client.get = mock_get

    results = await adapter.collect("xyznonexistent")
    assert results == []


# ── Request counting ─────────────────────────────────────────────────


async def test_request_count(mock_client):
    adapter = AppStoreAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(REVIEW_FEED))

    await adapter.collect("id:123456")
    assert adapter.request_count >= 1


# ── Close ────────────────────────────────────────────────────────────


async def test_close(mock_client):
    adapter = AppStoreAdapter(client=mock_client)
    await adapter.close()
    mock_client.aclose.assert_called_once()
