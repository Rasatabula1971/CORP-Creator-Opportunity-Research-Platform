"""Tests for the Patreon + Substack adapter — all HTTP calls mocked.

Fixture shapes are trimmed from real responses captured live against
substack.com while building this adapter (see its module docstring) --
not invented field names. Patreon is intentionally unimplemented in
this version (never verified live); tests for it assert graceful
no-op behavior, not real collection.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from corp.workers.adapters.patreon_substack import (
    PatreonSubstackAdapter,
    _extract_tiers,
    _parse_substack_date,
    _parse_substack_response,
    _section_names,
    _substack_url,
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


# ── Sample response (trimmed from a real capture) ─────────────────────

FREE_PUBLICATION = {
    "id": 90387,
    "name": "The Works in Progress Newsletter",
    "hero_text": "New and underrated ideas to improve the world.",
    "author_bio": "Works in Progress is a new online magazine.",
    "author_name": "Works in Progress",
    "created_at": "2020-09-02T03:51:44.742Z",
    "subdomain": "worksinprogress",
    "custom_domain": "www.worksinprogress.news",
    "payments_state": "disabled",
    "plans": None,
    "freeSubscriberCount": "58,000",
    "sections": [
        {"name": "Features"},
        {"name": "Notes on Progress"},
    ],
    "community_enabled": True,
    "has_recommendations": True,
}

PAID_PUBLICATION = {
    "id": 555111,
    "name": "Buyback Capital",
    "hero_text": "Deep dives on capital allocation.",
    "author_bio": None,
    "author_name": "Buyback Capital",
    "created_at": "2022-01-01T00:00:00Z",
    "subdomain": "buybackcapital",
    "custom_domain": None,
    "payments_state": "enabled",
    "plans": [
        {
            "id": "monthly109_99usd",
            "object": "plan",
            "amount": 10999,
            "currency": "usd",
            "interval": "month",
            "nickname": "$109.99 a month",
        }
    ],
    "freeSubscriberCount": "5,000",
    "sections": [],
    "community_enabled": False,
    "has_recommendations": False,
}

SUBSTACK_RESPONSE = {
    "items": [
        {"type": "post", "publication": FREE_PUBLICATION, "context": {}},
        # Same publication appears twice (two post hits) -- must dedup.
        {"type": "post", "publication": FREE_PUBLICATION, "context": {}},
        {"type": "post", "publication": PAID_PUBLICATION, "context": {}},
        # not "post" -- skipped
        {"type": "comment", "publication": FREE_PUBLICATION, "context": {}},
        {"type": "profileSearchResults", "results": []},  # no publication -- skipped
        {"type": "post", "publication": {"id": 999}},  # no name/description -- skipped
    ]
}


# ── Adapter properties ──────────────────────────────────────────────


def test_adapter_properties():
    adapter = PatreonSubstackAdapter()
    assert adapter.platform == "patreon_substack"
    assert adapter.family.value == "niche"
    assert adapter.access_method.value == "open"
    assert adapter.compliance_status.value == "verify"


# ── Substack parsing ──────────────────────────────────────────────────


def test_parse_substack_response_dedups_and_skips():
    results = _parse_substack_response(SUBSTACK_RESPONSE, "creator economy")
    assert len(results) == 2  # FREE_PUBLICATION deduped to one, PAID_PUBLICATION once

    ids = {r.external_id for r in results}
    assert len(ids) == 2  # genuinely distinct


def test_parse_substack_response_free_publication_fields():
    results = _parse_substack_response(SUBSTACK_RESPONSE, "creator economy")
    free = next(r for r in results if "Works in Progress" in r.text)

    assert free.content_type == "creator_page"
    assert free.source_platform == "patreon_substack"
    assert free.author == "Works in Progress"
    assert free.url == "https://www.worksinprogress.news"
    assert free.metadata["platform"] == "substack"
    assert free.metadata["payments_enabled"] is False
    assert free.metadata["tiers"] == []
    assert free.metadata["free_subscriber_count"] == "58,000"
    assert free.metadata["content_sections"] == ["Features", "Notes on Progress"]
    assert free.metadata["community_enabled"] is True
    assert free.compliance_status.value == "verify"


def test_parse_substack_response_paid_publication_has_tiers():
    results = _parse_substack_response(SUBSTACK_RESPONSE, "capital allocation")
    paid = next(r for r in results if "Buyback Capital" in r.text)

    assert paid.metadata["payments_enabled"] is True
    assert paid.metadata["tiers"] == [
        {
            "amount_cents": 10999,
            "currency": "usd",
            "interval": "month",
            "nickname": "$109.99 a month",
        }
    ]
    assert paid.url == "https://buybackcapital.substack.com"  # no custom_domain -- falls back


def test_parse_substack_response_no_items():
    assert _parse_substack_response({"items": []}, "q") == []
    assert _parse_substack_response({}, "q") == []


# ── Helper functions ───────────────────────────────────────────────────


def test_extract_tiers_disabled_payments_returns_empty():
    assert _extract_tiers({"payments_state": "disabled", "plans": [{"amount": 100}]}) == []


def test_extract_tiers_enabled_no_plans_returns_empty():
    assert _extract_tiers({"payments_state": "enabled", "plans": None}) == []


def test_section_names_missing():
    assert _section_names({}) == []


def test_substack_url_prefers_custom_domain():
    assert _substack_url({"custom_domain": "example.com", "subdomain": "example"}) == "https://example.com"


def test_substack_url_falls_back_to_subdomain():
    assert _substack_url({"custom_domain": None, "subdomain": "example"}) == "https://example.substack.com"


def test_substack_url_none_when_neither_present():
    assert _substack_url({}) is None


def test_parse_substack_date():
    dt = _parse_substack_date("2020-09-02T03:51:44.742Z")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2020, 9, 2)


def test_parse_substack_date_invalid():
    assert _parse_substack_date("not a date") is None
    assert _parse_substack_date(None) is None


# ── collect() via mocked HTTP ────────────────────────────────────────


async def test_collect_substack_prefix(mock_client):
    adapter = PatreonSubstackAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_json(SUBSTACK_RESPONSE))

    results = await adapter.collect("substack:creator economy")

    assert len(results) == 2
    assert all(r.metadata["platform"] == "substack" for r in results)
    call_kwargs = mock_client.get.call_args.kwargs
    assert call_kwargs["params"]["query"] == "creator economy"


async def test_collect_bare_query_only_hits_substack(mock_client):
    """Patreon is unimplemented -- a bare query must not error, and
    results come only from Substack."""
    adapter = PatreonSubstackAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_json(SUBSTACK_RESPONSE))

    results = await adapter.collect("creator economy")

    assert len(results) == 2
    assert all(r.metadata["platform"] == "substack" for r in results)
    mock_client.get.assert_called_once()  # never attempted an HTTP call for patreon


async def test_collect_patreon_prefix_returns_empty_not_raises():
    adapter = PatreonSubstackAdapter()
    results = await adapter.collect("patreon:creator economy")
    assert results == []


async def test_substack_failure_returns_empty_not_raises(mock_client):
    """Patreon always 'succeeds' with zero results (it's a documented
    no-op, not a failure), so a Substack failure alone must not trigger
    the all-platforms-failed RuntimeError -- it should just yield no
    results silently, matching the disclosed-gap design."""
    adapter = PatreonSubstackAdapter(client=mock_client)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))

    results = await adapter.collect("creator economy")
    assert results == []


# ── Max creators cap ──────────────────────────────────────────────────


async def test_max_creators_respected(mock_client):
    adapter = PatreonSubstackAdapter(max_creators=1, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_json(SUBSTACK_RESPONSE))

    results = await adapter.collect("substack:creator economy")
    assert len(results) == 1


# ── Request counting / close ─────────────────────────────────────────


async def test_request_count(mock_client):
    adapter = PatreonSubstackAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_json(SUBSTACK_RESPONSE))

    await adapter.collect("substack:creator economy")
    assert adapter.request_count >= 1


async def test_close(mock_client):
    adapter = PatreonSubstackAdapter(client=mock_client)
    await adapter.close()
    mock_client.aclose.assert_called_once()


# ── Capability conformance ───────────────────────────────────────────


async def test_implements_monetisation_provider(monkeypatch):
    """CORP1 Stage 5, T14: creator monetisation is MonetisationProvider,
    delegating to collect()."""
    from corp.workers.providers.capabilities import MonetisationProvider

    adapter = PatreonSubstackAdapter()
    assert isinstance(adapter, MonetisationProvider)

    sentinel: list[object] = []
    calls: list[str] = []

    async def fake_collect(identifier: str) -> list[object]:
        calls.append(identifier)
        return sentinel

    monkeypatch.setattr(adapter, "collect", fake_collect)

    assert await adapter.fetch_monetisation("creator economy") is sentinel
    assert calls == ["creator economy"]
