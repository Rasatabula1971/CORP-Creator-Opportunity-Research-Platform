"""Tests for the Google Trends adapter — all HTTP calls mocked."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from corp.workers.adapters.googletrends import (
    GoogleTrendsAdapter,
    _parse_trends_rss,
)


def _mock_resp_text(text: str, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.is_closed = False
    return client


TRENDS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
  <channel>
    <title>Trending</title>
    <item>
      <title>Python 4.0</title>
      <link>https://trends.google.com/trends/trendingsearches/daily?geo=US#Python+4.0</link>
      <pubDate>Mon, 15 Sep 2026 00:00:00 +0000</pubDate>
      <ht:approx_traffic>500,000+</ht:approx_traffic>
      <ht:news_item>
        <ht:news_item_title>Python 4.0 Released</ht:news_item_title>
        <ht:news_item_url>https://example.com/python4</ht:news_item_url>
      </ht:news_item>
    </item>
    <item>
      <title>AI Startup Funding</title>
      <link>https://trends.google.com/trends/trendingsearches/daily?geo=US#AI+Startup</link>
      <pubDate>Mon, 15 Sep 2026 00:00:00 +0000</pubDate>
      <ht:approx_traffic>200,000+</ht:approx_traffic>
    </item>
    <item>
      <title></title>
    </item>
  </channel>
</rss>"""


# ── Adapter properties ──────────────────────────────────────────────


def test_adapter_properties():
    adapter = GoogleTrendsAdapter()
    assert adapter.platform == "googletrends"
    assert adapter.family.value == "niche"
    assert adapter.access_method.value == "open"
    assert adapter.compliance_status.value == "compliant"


# ── RSS parsing ──────────────────────────────────────────────────────


def test_parse_trends_rss():
    results = _parse_trends_rss(TRENDS_RSS, "US")
    assert len(results) == 2

    r1 = results[0]
    assert r1.content_type == "trend"
    assert r1.source_platform == "googletrends"
    assert r1.text == "Python 4.0"
    assert r1.metadata["geo"] == "US"
    assert r1.metadata["approx_traffic"] == "500,000+"
    assert len(r1.metadata["news_items"]) == 1
    assert r1.metadata["news_items"][0]["title"] == "Python 4.0 Released"
    assert r1.compliance_status.value == "compliant"

    r2 = results[1]
    assert r2.text == "AI Startup Funding"
    assert r2.metadata["approx_traffic"] == "200,000+"


def test_parse_rss_empty_title_skipped():
    results = _parse_trends_rss(TRENDS_RSS, "US")
    titles = [r.text for r in results]
    assert "" not in titles


def test_parse_rss_invalid_xml():
    results = _parse_trends_rss("not xml at all", "US")
    assert results == []


# ── Trending collection ──────────────────────────────────────────────


async def test_collect_trending_default(mock_client):
    adapter = GoogleTrendsAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_text(TRENDS_RSS))

    results = await adapter.collect("trending")

    assert len(results) == 2
    assert all(r.content_type == "trend" for r in results)


async def test_collect_trending_with_geo(mock_client):
    adapter = GoogleTrendsAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_text(TRENDS_RSS))

    results = await adapter.collect("trending:GB")

    assert len(results) == 2


# ── Keyword fallback: keyword-matched trending only (no pytrends) ────


async def test_keyword_fallback_returns_only_matching_trends(mock_client):
    # TRENDS_RSS contains "Python 4.0" and "AI Startup Funding".
    adapter = GoogleTrendsAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_text(TRENDS_RSS))

    results = await adapter.collect("python")

    assert len(results) == 1
    assert results[0].text == "Python 4.0"


async def test_keyword_fallback_returns_empty_when_nothing_matches(mock_client):
    # No trending topic mentions this keyword → no unrelated items leak through.
    adapter = GoogleTrendsAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_text(TRENDS_RSS))

    results = await adapter.collect("underwater basket weaving")

    assert results == []


# ── Max items cap ────────────────────────────────────────────────────


async def test_max_items_respected(mock_client):
    adapter = GoogleTrendsAdapter(max_items=1, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_text(TRENDS_RSS))

    results = await adapter.collect("trending")
    assert len(results) == 1


# ── Empty RSS ────────────────────────────────────────────────────────


async def test_empty_rss(mock_client):
    empty_rss = '<?xml version="1.0"?><rss><channel></channel></rss>'
    adapter = GoogleTrendsAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_text(empty_rss))

    results = await adapter.collect("trending")
    assert results == []


# ── Request counting ─────────────────────────────────────────────────


async def test_request_count(mock_client):
    adapter = GoogleTrendsAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_text(TRENDS_RSS))

    await adapter.collect("trending")
    assert adapter.request_count >= 1


# ── Close ────────────────────────────────────────────────────────────


async def test_close(mock_client):
    adapter = GoogleTrendsAdapter(client=mock_client)
    await adapter.close()
    mock_client.aclose.assert_called_once()
