"""Tests for the marketplace adapter — all HTTP calls mocked."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from corp.workers.adapters.marketplace import (
    MarketplaceAdapter,
    _extract_price,
    _html_to_text,
    _parse_etsy_listings,
    _parse_gumroad_listings,
    _parse_udemy_response,
)


def _mock_resp_html(text: str, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


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


# ── Sample HTML ─────────────────────────────────────────────────────

GUMROAD_HTML = """
<div class="product-card" data-id="1">
    <a href="https://creator.gumroad.com/l/product1">
        <h3 class="product-card__title">Python Crash Course eBook</h3>
    </a>
    <span class="price">$29.00</span>
    <span class="product-card__creator">AuthorOne</span>
    <span>4.5 stars</span>
</div>
<div class="product-card" data-id="2">
    <a href="https://creator.gumroad.com/l/product2">
        <h3 class="product-card__title">Django Template Pack</h3>
    </a>
    <span class="price">$15.00</span>
    <span class="product-card__creator">AuthorTwo</span>
</div>
"""

ETSY_HTML = """
<div data-listing-id="1234567890" class="listing-card">
    <img alt="Printable Python Cheatsheet PDF" />
    <span class="currency-value">$12.99</span>
    <span class="shop-name">DigitalShopOne</span>
    <span>4.8 stars</span>
    <span>(1,234 reviews)</span>
    <a href="https://www.etsy.com/listing/1234567890/printable-python">link</a>
</div>
<div data-listing-id="9876543210" class="listing-card">
    <img alt="Coding Notebook Planner" />
    <span class="currency-value">$8.50</span>
    <span class="shop-name">DigitalShopTwo</span>
    <a href="https://www.etsy.com/listing/9876543210/coding-notebook">link</a>
</div>
"""

UDEMY_RESPONSE = {
    "results": [
        {
            "id": 12345,
            "title": "Complete Python Bootcamp",
            "headline": "Learn Python from scratch with hands-on projects",
            "url": "/course/complete-python-bootcamp/",
            "price_detail": {"amount": 19.99, "price_string": "$19.99"},
            "avg_rating": 4.6,
            "num_reviews": 50000,
            "num_subscribers": 200000,
            "visible_instructors": [{"display_name": "Prof Smith"}],
        },
        {
            "id": 67890,
            "title": "Advanced Django",
            "headline": "Master Django for production apps",
            "url": "/course/advanced-django/",
            "price_detail": {"amount": 24.99, "price_string": "$24.99"},
            "avg_rating": 4.3,
            "num_reviews": 8000,
            "num_subscribers": 30000,
            "visible_instructors": [{"display_name": "Dr Jones"}],
        },
    ]
}


# ── Adapter properties ──────────────────────────────────────────────


def test_adapter_properties():
    adapter = MarketplaceAdapter()
    assert adapter.platform == "marketplace"
    assert adapter.family.value == "niche"
    assert adapter.access_method.value == "open"
    assert adapter.compliance_status.value == "verify"


# ── Helper functions ────────────────────────────────────────────────


def test_html_to_text():
    assert _html_to_text("<p>Hello <b>world</b></p>") == "Hello world"
    assert _html_to_text("plain text") == "plain text"


def test_extract_price():
    assert _extract_price("$29.00") == 29.00
    assert _extract_price("$1,299.99") == 1299.99
    assert _extract_price("Free") is None
    assert _extract_price("") is None


# ── Gumroad parsing ────────────────────────────────────────────────


def test_parse_gumroad_listings():
    listings = _parse_gumroad_listings(GUMROAD_HTML, "python")
    assert len(listings) == 2

    g1 = listings[0]
    assert g1.content_type == "listing"
    assert g1.source_platform == "marketplace"
    assert "Python Crash Course" in g1.text
    assert g1.metadata["marketplace"] == "gumroad"
    assert g1.metadata["price"] == 29.00
    assert g1.metadata["rating"] == 4.5
    assert g1.author == "AuthorOne"

    g2 = listings[1]
    assert "Django Template Pack" in g2.text
    assert g2.metadata["price"] == 15.00


def test_parse_gumroad_empty():
    assert _parse_gumroad_listings("<html>nothing</html>", "q") == []


# ── Etsy parsing ───────────────────────────────────────────────────


def test_parse_etsy_listings():
    listings = _parse_etsy_listings(ETSY_HTML, "python")
    assert len(listings) == 2

    e1 = listings[0]
    assert e1.content_type == "listing"
    assert e1.external_id == "etsy_1234567890"
    assert "Printable Python Cheatsheet" in e1.text
    assert e1.metadata["marketplace"] == "etsy"
    assert e1.metadata["price"] == 12.99
    assert e1.metadata["rating"] == 4.8
    assert e1.metadata["review_count"] == 1234
    assert e1.author == "DigitalShopOne"

    e2 = listings[1]
    assert e2.external_id == "etsy_9876543210"
    assert "Coding Notebook" in e2.text
    assert e2.metadata["price"] == 8.50


def test_parse_etsy_empty():
    assert _parse_etsy_listings("<html>nothing</html>", "q") == []


# ── Udemy parsing ──────────────────────────────────────────────────


def test_parse_udemy_response():
    listings = _parse_udemy_response(UDEMY_RESPONSE, "python")
    assert len(listings) == 2

    u1 = listings[0]
    assert u1.content_type == "listing"
    assert u1.external_id == "udemy_12345"
    assert "Complete Python Bootcamp" in u1.text
    assert "hands-on projects" in u1.text
    assert u1.metadata["marketplace"] == "udemy"
    assert u1.metadata["price"] == 19.99
    assert u1.metadata["rating"] == 4.6
    assert u1.metadata["review_count"] == 50000
    assert u1.metadata["subscriber_count"] == 200000
    assert u1.author == "Prof Smith"
    assert u1.url == "https://www.udemy.com/course/complete-python-bootcamp/"

    u2 = listings[1]
    assert u2.external_id == "udemy_67890"
    assert u2.metadata["price"] == 24.99


def test_parse_udemy_empty():
    assert _parse_udemy_response({"results": []}, "q") == []
    assert _parse_udemy_response({}, "q") == []


# ── collect with prefix ────────────────────────────────────────────


async def test_collect_gumroad_prefix(mock_client):
    adapter = MarketplaceAdapter(max_listings=10, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_html(GUMROAD_HTML))

    results = await adapter.collect("gumroad:python")

    assert len(results) == 2
    assert all(r.metadata["marketplace"] == "gumroad" for r in results)


async def test_collect_etsy_prefix(mock_client):
    adapter = MarketplaceAdapter(max_listings=10, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_html(ETSY_HTML))

    results = await adapter.collect("etsy:python")

    assert len(results) == 2
    assert all(r.metadata["marketplace"] == "etsy" for r in results)


async def test_collect_udemy_prefix(mock_client):
    adapter = MarketplaceAdapter(max_listings=10, client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_json(UDEMY_RESPONSE))

    results = await adapter.collect("udemy:python")

    assert len(results) == 2
    assert all(r.metadata["marketplace"] == "udemy" for r in results)


# ── collect bare query (all marketplaces) ──────────────────────────


async def test_collect_all_marketplaces(mock_client):
    adapter = MarketplaceAdapter(max_listings=30, client=mock_client)

    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        url_str = str(url)
        if "gumroad" in url_str:
            return _mock_resp_html(GUMROAD_HTML)
        if "etsy" in url_str:
            return _mock_resp_html(ETSY_HTML)
        if "udemy" in url_str:
            return _mock_resp_json(UDEMY_RESPONSE)
        return _mock_resp_html("<html>empty</html>")

    mock_client.get = mock_get

    results = await adapter.collect("python")

    marketplaces = {r.metadata["marketplace"] for r in results}
    assert "gumroad" in marketplaces
    assert "etsy" in marketplaces
    assert "udemy" in marketplaces
    assert len(results) == 6


# ── max_listings cap ───────────────────────────────────────────────


async def test_max_listings_respected(mock_client):
    adapter = MarketplaceAdapter(max_listings=3, client=mock_client)

    async def mock_get(url, **kwargs):
        url_str = str(url)
        if "gumroad" in url_str:
            return _mock_resp_html(GUMROAD_HTML)
        if "etsy" in url_str:
            return _mock_resp_html(ETSY_HTML)
        if "udemy" in url_str:
            return _mock_resp_json(UDEMY_RESPONSE)
        return _mock_resp_html("")

    mock_client.get = mock_get

    results = await adapter.collect("python")
    assert len(results) <= 3


# ── empty results ──────────────────────────────────────────────────


async def test_empty_results(mock_client):
    adapter = MarketplaceAdapter(client=mock_client)

    async def mock_get(url, **kwargs):
        url_str = str(url)
        if "udemy" in url_str:
            return _mock_resp_json({"results": []})
        return _mock_resp_html("<html>nothing</html>")

    mock_client.get = mock_get

    results = await adapter.collect("xyznonexistent")
    assert results == []


# ── request counting ──────────────────────────────────────────────


async def test_request_count(mock_client):
    adapter = MarketplaceAdapter(
        marketplaces=["gumroad"],
        client=mock_client,
    )
    mock_client.get = AsyncMock(return_value=_mock_resp_html(GUMROAD_HTML))

    await adapter.collect("gumroad:python")
    assert adapter.request_count >= 1


# ── custom marketplace list ────────────────────────────────────────


async def test_custom_marketplace_list(mock_client):
    adapter = MarketplaceAdapter(
        marketplaces=["etsy"],
        max_listings=10,
        client=mock_client,
    )
    mock_client.get = AsyncMock(return_value=_mock_resp_html(ETSY_HTML))

    results = await adapter.collect("printable planner")

    assert len(results) > 0
    assert all(r.metadata["marketplace"] == "etsy" for r in results)


# ── per-marketplace isolation ──────────────────────────────────────


async def test_one_marketplace_failure_is_isolated(mock_client):
    adapter = MarketplaceAdapter(max_listings=30, client=mock_client)

    async def mock_get(url, **kwargs):
        url_str = str(url)
        if "udemy" in url_str:
            raise httpx.TransportError("udemy 403")
        if "gumroad" in url_str:
            return _mock_resp_html(GUMROAD_HTML)
        if "etsy" in url_str:
            return _mock_resp_html(ETSY_HTML)
        return _mock_resp_html("")

    mock_client.get = mock_get

    # Udemy blows up, but Gumroad and Etsy listings still come back.
    results = await adapter.collect("python")
    marketplaces = {r.metadata["marketplace"] for r in results}
    assert "gumroad" in marketplaces
    assert "etsy" in marketplaces
    assert "udemy" not in marketplaces


async def test_all_marketplaces_failing_raises(mock_client):
    adapter = MarketplaceAdapter(max_listings=30, client=mock_client)

    async def mock_get(url, **kwargs):
        raise httpx.TransportError("everything down")

    mock_client.get = mock_get

    with pytest.raises(RuntimeError, match="All marketplaces failed"):
        await adapter.collect("python")


def test_implements_transaction_and_solution_provider():
    """CORP1 Stage 4/5, T2: Marketplace is both TransactionProvider and
    SolutionProvider, but (audit fix) fetch_transactions no longer treats
    every listing as a sale — see the tests below."""
    from corp.workers.providers.capabilities import SolutionProvider, TransactionProvider

    adapter = MarketplaceAdapter()
    assert isinstance(adapter, TransactionProvider)
    assert isinstance(adapter, SolutionProvider)


async def test_fetch_solutions_returns_every_listing(mock_client):
    """A listing existing is solution evidence regardless of sales proof."""
    adapter = MarketplaceAdapter(marketplaces=["gumroad"], client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_html(GUMROAD_HTML))

    results = await adapter.fetch_solutions("python")
    assert len(results) == 2


async def test_fetch_transactions_excludes_gumroad_listings(mock_client):
    """Gumroad's discover page carries no purchase-count signal, so a
    Gumroad listing alone must never count as a transaction."""
    adapter = MarketplaceAdapter(marketplaces=["gumroad"], client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_html(GUMROAD_HTML))

    assert await adapter.fetch_transactions("python") == []


async def test_fetch_transactions_keeps_udemy_courses_with_subscribers(mock_client):
    adapter = MarketplaceAdapter(marketplaces=["udemy"], client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_json(UDEMY_RESPONSE))

    results = await adapter.fetch_transactions("python")
    assert len(results) == 2
    assert all(r.metadata["subscriber_count"] for r in results)


async def test_fetch_transactions_excludes_udemy_courses_without_subscribers(mock_client):
    no_subs = {
        "results": [
            {
                "id": 1,
                "title": "Brand New Course",
                "headline": "Just published",
                "url": "/course/brand-new/",
                "price_detail": {"amount": 9.99, "price_string": "$9.99"},
                "num_subscribers": 0,
                "visible_instructors": [],
            }
        ]
    }
    adapter = MarketplaceAdapter(marketplaces=["udemy"], client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_json(no_subs))

    assert await adapter.fetch_transactions("python") == []


async def test_fetch_transactions_keeps_etsy_listings_with_reviews(mock_client):
    adapter = MarketplaceAdapter(marketplaces=["etsy"], client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp_html(ETSY_HTML))

    results = await adapter.fetch_transactions("python")
    # Only the first ETSY_HTML listing has a parsed review count.
    assert len(results) == 1
    assert results[0].metadata["review_count"] == 1234


async def test_fetch_transactions_excludes_etsy_api_favorites(mock_client):
    """num_favorers is a wishlist count, not a sale — must not leak into
    review_count and get counted as a transaction."""
    from corp.workers.adapters.marketplace import _parse_etsy_api_response

    data = {
        "results": [
            {
                "listing_id": 1,
                "title": "Popular but unsold",
                "num_favorers": 500,
                "price": {"amount": 1000, "divisor": 100},
            }
        ]
    }
    [item] = _parse_etsy_api_response(data, "python")
    assert item.metadata["review_count"] is None
    assert item.metadata["favorite_count"] == 500

    from corp.workers.adapters.marketplace import _has_transaction_evidence

    assert _has_transaction_evidence(item) is False


async def test_collect_is_single_flight_across_capabilities(mock_client):
    """T3 fans a keyword out across every capability an adapter implements;
    fetch_solutions and fetch_transactions must not each trigger their own
    full round of marketplace HTTP requests for the same identifier."""
    import asyncio

    adapter = MarketplaceAdapter(marketplaces=["gumroad", "etsy", "udemy"], client=mock_client)
    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        url_str = str(url)
        if "gumroad" in url_str:
            return _mock_resp_html(GUMROAD_HTML)
        if "etsy" in url_str:
            return _mock_resp_html(ETSY_HTML)
        return _mock_resp_json(UDEMY_RESPONSE)

    mock_client.get = mock_get

    solutions, transactions = await asyncio.gather(
        adapter.fetch_solutions("python"), adapter.fetch_transactions("python")
    )

    assert len(solutions) == 6
    assert {r.metadata["marketplace"] for r in transactions} == {"etsy", "udemy"}
    assert call_count == 3, "one request per marketplace, not one per capability"


async def test_fetch_transactions_mixed_marketplaces(mock_client):
    adapter = MarketplaceAdapter(marketplaces=["gumroad", "etsy", "udemy"], client=mock_client)

    async def mock_get(url, **kwargs):
        url_str = str(url)
        if "gumroad" in url_str:
            return _mock_resp_html(GUMROAD_HTML)
        if "etsy" in url_str:
            return _mock_resp_html(ETSY_HTML)
        return _mock_resp_json(UDEMY_RESPONSE)

    mock_client.get = mock_get

    results = await adapter.fetch_transactions("python")
    marketplaces = {r.metadata["marketplace"] for r in results}
    assert marketplaces == {"etsy", "udemy"}, "gumroad listings must never appear here"
