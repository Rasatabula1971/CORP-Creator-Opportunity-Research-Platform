"""Tests for the crowdfunding adapter — all HTTP calls mocked.

Fixture shapes are trimmed from real responses captured live against
kickstarter.com and indiegogo.com while building this adapter (see its
module docstring) -- not invented field names.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from corp.workers.adapters.crowdfunding import (
    CrowdfundingAdapter,
    _parse_indiegogo_date,
    _parse_indiegogo_response,
    _parse_kickstarter_response,
)


def _mock_resp_json(data: dict, status: int = 200) -> MagicMock:
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


# ── Sample responses (trimmed from real captures) ────────────────────

KICKSTARTER_RESPONSE = {
    "projects": [
        {
            "id": 1816684671,
            "name": "Espresso Buffet",
            "blurb": "Espresso and pastries -- we're opening a shop!",
            "goal": 20000,
            "pledged": 21061,
            "state": "successful",
            "backers_count": 148,
            "percent_funded": 105.305,
            "currency": "EUR",
            "launched_at": 1680166623,
            "creator": {"name": "Espresso Buffet"},
            "category": {"name": "Restaurants"},
            "urls": {"web": {"project": "https://www.kickstarter.com/projects/burggasse57/espresso-buffet"}},
        },
        {
            "id": 999,
            "name": "",  # no name -- must be skipped (no text)
            "blurb": "",
            "state": "failed",
        },
    ],
    "total_hits": 2,
}

INDIEGOGO_RESPONSE = {
    "pagedItems": [
        {
            "projectID": 18126,
            "name": "Advanced Espresso: Elements of Coffee",
            "shortDescription": "The fundamentals of how to achieve maximum extraction/taste.",
            "creatorName": "ROBERT ALOE",
            "publishedDate": "2023-11-30T00:00:00Z",
            "projectPageUrl": "https://www.indiegogo.com/en/projects/robertaloe/advanced-espresso-elements-of-coffee",
            "catalogCategory": 60,
            "campaignOutcome": 0,
            "campaignGoal": None,
        },
        {
            "projectID": 83367,
            "name": "STARESSO MINI: The World's Smallest Espresso Maker",
            "shortDescription": "Make a barista-worthy espresso in seconds wherever you go.",
            "creatorName": "MINI STARESSO",
            "publishedDate": "2020-01-28T00:00:00Z",
            "projectPageUrl": "https://www.indiegogo.com/en/projects/ministaresso/staresso-mini",
            "catalogCategory": 50,
            "campaignOutcome": 1,
            "campaignGoal": 2000,
        },
    ],
    "totalItemCount": 62,
}


# ── Adapter properties ──────────────────────────────────────────────


def test_adapter_properties():
    adapter = CrowdfundingAdapter()
    assert adapter.platform == "crowdfunding"
    assert adapter.family.value == "niche"
    assert adapter.access_method.value == "open"
    assert adapter.compliance_status.value == "verify"


# ── Kickstarter parsing ───────────────────────────────────────────────


def test_parse_kickstarter_response():
    results = _parse_kickstarter_response(KICKSTARTER_RESPONSE, "home espresso")
    assert len(results) == 1  # the empty-name project is skipped

    r = results[0]
    assert r.content_type == "project"
    assert r.source_platform == "crowdfunding"
    assert "Espresso Buffet" in r.text
    assert r.author == "Espresso Buffet"
    assert r.url == "https://www.kickstarter.com/projects/burggasse57/espresso-buffet"
    assert r.metadata["platform"] == "kickstarter"
    assert r.metadata["state"] == "successful"
    assert r.metadata["goal"] == 20000
    assert r.metadata["pledged"] == 21061
    assert r.metadata["backers_count"] == 148
    assert r.metadata["percent_funded"] == 105.305
    assert r.metadata["category"] == "Restaurants"
    assert r.compliance_status.value == "verify"


def test_parse_kickstarter_response_no_projects():
    assert _parse_kickstarter_response({"projects": []}, "q") == []
    assert _parse_kickstarter_response({}, "q") == []


# ── Indiegogo parsing ─────────────────────────────────────────────────


def test_parse_indiegogo_response():
    results = _parse_indiegogo_response(INDIEGOGO_RESPONSE, "espresso")
    assert len(results) == 2

    r = results[0]
    assert r.content_type == "project"
    assert r.source_platform == "crowdfunding"
    assert "Advanced Espresso" in r.text
    assert r.author == "ROBERT ALOE"
    assert r.url == "https://www.indiegogo.com/en/projects/robertaloe/advanced-espresso-elements-of-coffee"
    assert r.metadata["platform"] == "indiegogo"
    assert r.metadata["catalog_category_id"] == 60
    assert r.metadata["campaign_outcome_raw"] == 0
    assert r.metadata["campaign_goal"] is None
    assert r.compliance_status.value == "verify"


def test_parse_indiegogo_response_no_items():
    assert _parse_indiegogo_response({"pagedItems": []}, "q") == []
    assert _parse_indiegogo_response({}, "q") == []


def test_parse_indiegogo_date():
    dt = _parse_indiegogo_date("2023-11-30T00:00:00Z")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2023, 11, 30)


def test_parse_indiegogo_date_invalid():
    assert _parse_indiegogo_date("not a date") is None
    assert _parse_indiegogo_date(None) is None


# ── collect() via mocked HTTP ────────────────────────────────────────


async def test_collect_kickstarter_prefix(mock_client):
    adapter = CrowdfundingAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_json(KICKSTARTER_RESPONSE))

    results = await adapter.collect("kickstarter:home espresso")

    assert len(results) == 1
    assert results[0].metadata["platform"] == "kickstarter"
    mock_client.get.assert_called_once()
    call_kwargs = mock_client.get.call_args.kwargs
    assert call_kwargs["params"]["term"] == "home espresso"


async def test_collect_indiegogo_prefix(mock_client):
    adapter = CrowdfundingAdapter(client=mock_client)
    mock_client.post = AsyncMock(return_value=_mock_resp_json(INDIEGOGO_RESPONSE))

    results = await adapter.collect("indiegogo:espresso")

    assert len(results) == 2
    assert all(r.metadata["platform"] == "indiegogo" for r in results)
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["json"]["term"] == "espresso"


async def test_collect_bare_query_hits_both_platforms(mock_client):
    adapter = CrowdfundingAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_json(KICKSTARTER_RESPONSE))
    mock_client.post = AsyncMock(return_value=_mock_resp_json(INDIEGOGO_RESPONSE))

    results = await adapter.collect("espresso")

    platforms = {r.metadata["platform"] for r in results}
    assert platforms == {"kickstarter", "indiegogo"}


async def test_one_platform_failing_does_not_lose_the_other(mock_client):
    adapter = CrowdfundingAdapter(client=mock_client)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    mock_client.post = AsyncMock(return_value=_mock_resp_json(INDIEGOGO_RESPONSE))

    results = await adapter.collect("espresso")

    assert len(results) == 2
    assert all(r.metadata["platform"] == "indiegogo" for r in results)


async def test_both_platforms_failing_raises(mock_client):
    adapter = CrowdfundingAdapter(client=mock_client)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(RuntimeError, match="All crowdfunding platforms failed"):
        await adapter.collect("espresso")


# ── Max projects cap ──────────────────────────────────────────────────


async def test_max_projects_respected(mock_client):
    adapter = CrowdfundingAdapter(max_projects=1, client=mock_client)
    mock_client.post = AsyncMock(return_value=_mock_resp_json(INDIEGOGO_RESPONSE))

    results = await adapter.collect("indiegogo:espresso")
    assert len(results) == 1


# ── Request counting / close ─────────────────────────────────────────


async def test_request_count(mock_client):
    adapter = CrowdfundingAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_json(KICKSTARTER_RESPONSE))

    await adapter.collect("kickstarter:espresso")
    assert adapter.request_count >= 1


async def test_close(mock_client):
    adapter = CrowdfundingAdapter(client=mock_client)
    await adapter.close()
    mock_client.aclose.assert_called_once()


# ── Capability conformance ───────────────────────────────────────────


async def test_implements_transaction_provider(monkeypatch):
    """CORP1 Stage 5, T13: crowdfunding backing is TransactionProvider,
    delegating to collect()."""
    from corp.workers.providers.capabilities import TransactionProvider

    adapter = CrowdfundingAdapter()
    assert isinstance(adapter, TransactionProvider)

    sentinel: list[object] = []
    calls: list[str] = []

    async def fake_collect(identifier: str) -> list[object]:
        calls.append(identifier)
        return sentinel

    monkeypatch.setattr(adapter, "collect", fake_collect)

    assert await adapter.fetch_transactions("espresso") is sentinel
    assert calls == ["espresso"]
