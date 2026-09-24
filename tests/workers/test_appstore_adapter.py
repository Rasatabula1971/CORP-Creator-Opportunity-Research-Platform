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


def test_parse_uses_entry_updated_timestamp():
    feed = {
        "feed": {
            "entry": [
                {
                    "id": {"label": "7001"},
                    "title": {"label": "Old review"},
                    "content": {"label": "text"},
                    "im:rating": {"label": "2"},
                    "author": {"name": {"label": "R"}},
                    "im:name": {"label": "App"},
                    "updated": {"label": "2024-03-15T10:30:00-07:00"},
                }
            ]
        }
    }
    results = _parse_review_feed(feed, "1")
    assert len(results) == 1
    ts = results[0].timestamp
    assert ts.year == 2024 and ts.month == 3 and ts.day == 15
    # -07:00 10:30 → 17:30 UTC
    assert ts.hour == 17


async def test_reviews_url_includes_country(mock_client):
    adapter = AppStoreAdapter(country="gb", client=mock_client)
    seen_urls: list[str] = []

    async def mock_get(url, **kwargs):
        seen_urls.append(str(url))
        return _mock_resp(REVIEW_FEED)

    mock_client.get = mock_get

    await adapter.collect("id:123456")
    assert any("/gb/rss/customerreviews/" in u for u in seen_urls)


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


def test_implements_solution_and_dissatisfaction_provider():
    """CORP1 Stage 4/5, T2: App Store is both SolutionProvider and
    DissatisfactionProvider, but (audit fix) each has its own semantics —
    see the tests below, not identical delegation to collect()."""
    from corp.workers.providers.capabilities import DissatisfactionProvider, SolutionProvider

    adapter = AppStoreAdapter()
    assert isinstance(adapter, SolutionProvider)
    assert isinstance(adapter, DissatisfactionProvider)


# ── fetch_solutions: one item per app, not per review ────────────────


async def test_fetch_solutions_by_search_returns_one_item_per_app(mock_client):
    adapter = AppStoreAdapter(max_apps=2, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(SEARCH_RESPONSE))

    results = await adapter.fetch_solutions("search:cool app")

    assert len(results) == 2
    assert all(r.content_type == "app_listing" for r in results)
    assert {r.metadata["app_id"] for r in results} == {"123456", "789012"}
    # Never hits the reviews endpoint at all for this path.
    called_urls = [str(c.args[0]) for c in mock_client.get.await_args_list]
    assert all("rss/customerreviews" not in u for u in called_urls)


async def test_fetch_solutions_by_id_uses_lookup_not_reviews(mock_client):
    adapter = AppStoreAdapter(client=mock_client)
    lookup_result = {
        "results": [{"trackId": 123456, "trackName": "CoolApp Pro", "sellerName": "Acme"}]
    }
    mock_client.get = AsyncMock(return_value=_mock_resp(lookup_result))

    results = await adapter.fetch_solutions("id:123456")

    assert len(results) == 1
    assert results[0].content_type == "app_listing"
    assert results[0].metadata["app_id"] == "123456"
    assert results[0].author == "Acme"
    called_url = str(mock_client.get.await_args.args[0])
    assert "lookup" in called_url


async def test_fetch_solutions_bare_keyword_matches_search_semantics(mock_client):
    adapter = AppStoreAdapter(max_apps=5, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(SEARCH_RESPONSE))

    results = await adapter.fetch_solutions("productivity")
    assert len(results) == 2


async def test_fetch_solutions_unknown_app_id_is_empty(mock_client):
    adapter = AppStoreAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp({"results": []}))

    assert await adapter.fetch_solutions("id:999999") == []


# ── fetch_dissatisfaction: only low-star reviews ─────────────────────

MIXED_RATING_FEED = {
    "feed": {
        "entry": [
            {
                "id": {"label": "1"},
                "title": {"label": "Love it"},
                "content": {"label": "Five stars, no notes."},
                "im:rating": {"label": "5"},
                "author": {"name": {"label": "Happy"}},
                "im:name": {"label": "CoolApp Pro"},
            },
            {
                "id": {"label": "2"},
                "title": {"label": "It's fine"},
                "content": {"label": "Does the job."},
                "im:rating": {"label": "4"},
                "author": {"name": {"label": "Neutral"}},
                "im:name": {"label": "CoolApp Pro"},
            },
            {
                "id": {"label": "3"},
                "title": {"label": "Frustrating"},
                "content": {"label": "Missing basic features."},
                "im:rating": {"label": "2"},
                "author": {"name": {"label": "Unhappy"}},
                "im:name": {"label": "CoolApp Pro"},
            },
            {
                "id": {"label": "4"},
                "title": {"label": "Terrible"},
                "content": {"label": "Crashes constantly."},
                "im:rating": {"label": "1"},
                "author": {"name": {"label": "Furious"}},
                "im:name": {"label": "CoolApp Pro"},
            },
        ]
    }
}


async def test_fetch_dissatisfaction_excludes_high_star_reviews(mock_client):
    adapter = AppStoreAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(MIXED_RATING_FEED))

    results = await adapter.fetch_dissatisfaction("id:123456")

    ratings = {r.metadata["star_rating"] for r in results}
    assert ratings == {2, 1}, "a 5-star or 4-star review must not count as dissatisfaction"


async def test_dissatisfaction_max_stars_is_configurable(mock_client):
    adapter = AppStoreAdapter(client=mock_client, dissatisfaction_max_stars=1)
    mock_client.get = AsyncMock(return_value=_mock_resp(MIXED_RATING_FEED))

    results = await adapter.fetch_dissatisfaction("id:123456")

    assert {r.metadata["star_rating"] for r in results} == {1}


async def test_fetch_dissatisfaction_excludes_unparseable_ratings(mock_client):
    feed = {
        "feed": {
            "entry": [
                {
                    "id": {"label": "1"},
                    "title": {"label": "App Info"},
                    "content": {"label": "no rating field parses"},
                    "im:rating": {"label": "not-a-number"},
                    "im:name": {"label": "CoolApp Pro"},
                },
            ]
        }
    }
    adapter = AppStoreAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(feed))

    assert await adapter.fetch_dissatisfaction("id:123456") == []
