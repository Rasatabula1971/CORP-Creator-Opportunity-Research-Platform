"""Tests for the Hacker News adapter — all HTTP calls mocked."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from corp.workers.adapters.hackernews import HackerNewsAdapter, _parse_ts


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


STORY_RESPONSE = {
    "hits": [
        {
            "objectID": "111",
            "title": "Show HN: My Python tool",
            "story_text": "Built a CLI for research.",
            "author": "pg",
            "url": "https://example.com/tool",
            "points": 150,
            "num_comments": 42,
            "created_at_i": 1700000000,
            "_tags": ["story", "show_hn"],
        },
        {
            "objectID": "222",
            "title": "Ask HN: Best API for data?",
            "story_text": "",
            "author": "dang",
            "url": None,
            "points": 80,
            "num_comments": 25,
            "created_at_i": 1700001000,
            "_tags": ["story", "ask_hn"],
        },
    ],
    "nbPages": 1,
}

COMMENT_RESPONSE = {
    "hits": [
        {
            "objectID": "333",
            "comment_text": "This is <b>great</b>! I needed this.",
            "author": "commenter1",
            "story_id": 111,
            "story_title": "Show HN: My Python tool",
            "story_url": "https://example.com/tool",
            "points": None,
            "created_at_i": 1700002000,
            "_tags": ["comment"],
        },
    ],
    "nbPages": 1,
}


# ── Adapter properties ──────────────────────────────────────────────


def test_adapter_properties():
    adapter = HackerNewsAdapter()
    assert adapter.platform == "hackernews"
    assert adapter.family.value == "niche"
    assert adapter.access_method.value == "open"
    assert adapter.compliance_status.value == "compliant"


# ── _parse_ts helper ─────────────────────────────────────────────────


def test_parse_ts_valid():
    dt = _parse_ts(1700000000)
    assert dt is not None
    assert dt.year == 2023


def test_parse_ts_none():
    assert _parse_ts(None) is None


# ── Story collection ─────────────────────────────────────────────────


async def test_collect_stories(mock_client):
    adapter = HackerNewsAdapter(max_items=10, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(STORY_RESPONSE))

    results = await adapter.collect("python tool")

    assert len(results) == 2
    s1 = results[0]
    assert s1.content_type == "story"
    assert s1.source_platform == "hackernews"
    assert s1.external_id == "111"
    assert "Python tool" in s1.text
    assert "CLI for research" in s1.text
    assert s1.author == "pg"
    assert s1.metadata["like_count"] == 150
    assert s1.metadata["comment_count"] == 42
    assert s1.url == "https://example.com/tool"

    s2 = results[1]
    assert s2.external_id == "222"
    assert s2.text == "Ask HN: Best API for data?"


# ── Comment collection ───────────────────────────────────────────────


async def test_collect_comments(mock_client):
    adapter = HackerNewsAdapter(max_items=10, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(COMMENT_RESPONSE))

    results = await adapter.collect("comments:python")

    assert len(results) == 1
    c = results[0]
    assert c.content_type == "comment"
    assert c.external_id == "333"
    assert "great" in c.text
    assert "<b>" not in c.text
    assert c.parent_id == "111"
    assert c.metadata["story_title"] == "Show HN: My Python tool"


# ── Show HN prefix ──────────────────────────────────────────────────


async def test_collect_show_hn(mock_client):
    adapter = HackerNewsAdapter(max_items=10, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(STORY_RESPONSE))

    results = await adapter.collect("show:python")
    assert len(results) == 2


# ── Max items cap ────────────────────────────────────────────────────


async def test_max_items_respected(mock_client):
    adapter = HackerNewsAdapter(max_items=1, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(STORY_RESPONSE))

    results = await adapter.collect("python")
    assert len(results) == 1


# ── Empty results ────────────────────────────────────────────────────


async def test_empty_results(mock_client):
    adapter = HackerNewsAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp({"hits": [], "nbPages": 0}))

    results = await adapter.collect("xyznonexistent")
    assert results == []


# ── Skips hits without title ─────────────────────────────────────────


async def test_skips_empty_title(mock_client):
    adapter = HackerNewsAdapter(client=mock_client)
    data = {"hits": [{"objectID": "999", "title": "", "author": "x"}], "nbPages": 1}
    mock_client.get = AsyncMock(return_value=_mock_resp(data))

    results = await adapter.collect("test")
    assert results == []


# ── Request counting ─────────────────────────────────────────────────


async def test_request_count(mock_client):
    adapter = HackerNewsAdapter(max_items=5, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp(STORY_RESPONSE))

    await adapter.collect("python")
    assert adapter.request_count >= 1


# ── Close ────────────────────────────────────────────────────────────


async def test_close(mock_client):
    adapter = HackerNewsAdapter(client=mock_client)
    await adapter.close()
    mock_client.aclose.assert_called_once()


async def test_implements_problem_provider(monkeypatch):
    """CORP1 Stage 4/5, T2: Hacker News is ProblemProvider, delegating to collect()."""
    from corp.workers.providers.capabilities import ProblemProvider

    adapter = HackerNewsAdapter()
    assert isinstance(adapter, ProblemProvider)

    sentinel: list[object] = []
    calls: list[str] = []

    async def fake_collect(identifier: str) -> list[object]:
        calls.append(identifier)
        return sentinel

    monkeypatch.setattr(adapter, "collect", fake_collect)

    assert await adapter.fetch_problems("django") is sentinel
    assert calls == ["django"]
