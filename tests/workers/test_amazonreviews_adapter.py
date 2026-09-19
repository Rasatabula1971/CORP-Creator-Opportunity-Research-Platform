"""Tests for the Amazon review adapter — all HTTP calls mocked."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from corp.workers.adapters.amazonreviews import (
    MAX_REVIEW_PAGES,
    STAR_FILTER,
    AmazonReviewAdapter,
    _extract_asins,
    _html_to_text,
    _parse_review_date,
    _parse_reviews,
)


def _mock_resp(text: str, status: int = 200) -> MagicMock:
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


SAMPLE_REVIEW_HTML = """
<div data-hook="review" id="R1ABC123">
    <span data-hook="review-star-rating">
        <span>2.0 out of 5 stars</span>
    </span>
    <a data-hook="review-title"><span>Disappointing quality</span></a>
    <span class="a-profile-name">Jane Doe</span>
    <span data-hook="review-date">Reviewed in the United States on March 15, 2024</span>
    <span data-hook="review-body"><span>The product broke after two weeks of normal use.
    Very disappointed with the build quality.</span></span>
</div>
<div data-hook="review" id="R2DEF456">
    <span data-hook="review-star-rating">
        <span>1.0 out of 5 stars</span>
    </span>
    <a data-hook="review-title"><span>Does not work</span></a>
    <span class="a-profile-name">John Smith</span>
    <span data-hook="review-date">Reviewed in the United States on February 1, 2024</span>
    <span data-hook="review-body"><span>Arrived broken. Would not recommend.</span></span>
</div>
"""

SAMPLE_SEARCH_HTML = """
<div data-asin="B08N5WRWNW" class="s-result-item">product 1</div>
<div data-asin="B09XYZ1234" class="s-result-item">product 2</div>
<div data-asin="" class="s-result-item">empty asin</div>
<div data-asin="B08N5WRWNW" class="s-result-item">duplicate</div>
"""


# ── Adapter properties ──────────────────────────────────────────────


def test_adapter_properties():
    adapter = AmazonReviewAdapter()
    assert adapter.platform == "amazon_reviews"
    assert adapter.family.value == "niche"
    assert adapter.access_method.value == "open"
    assert adapter.compliance_status.value == "verify"


# ── HTML parsing helpers ────────────────────────────────────────────


def test_html_to_text():
    assert _html_to_text("<p>Hello <b>world</b></p>") == "Hello world"
    assert _html_to_text("plain text") == "plain text"


def test_extract_asins():
    asins = _extract_asins(SAMPLE_SEARCH_HTML)
    assert asins == ["B08N5WRWNW", "B09XYZ1234"]


def test_parse_review_date():
    dt = _parse_review_date("Reviewed in the United States on March 15, 2024")
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 3
    assert dt.day == 15

    assert _parse_review_date("no date here") is None
    assert _parse_review_date("") is None


# ── Review parsing ──────────────────────────────────────────────────


def test_parse_reviews():
    reviews = _parse_reviews(SAMPLE_REVIEW_HTML, "B08TEST123")
    assert len(reviews) == 2

    r1 = reviews[0]
    assert r1.external_id == "R1ABC123"
    assert r1.content_type == "review"
    assert r1.source_platform == "amazon_reviews"
    assert "Disappointing quality" in r1.text
    assert "broke after two weeks" in r1.text
    assert r1.metadata["asin"] == "B08TEST123"
    assert r1.metadata["star_rating"] == 2.0

    r2 = reviews[1]
    assert r2.external_id == "R2DEF456"
    assert "Does not work" in r2.text
    assert r2.metadata["star_rating"] == 1.0


def test_parse_reviews_empty_html():
    reviews = _parse_reviews("<html><body>No reviews</body></html>", "B00000")
    assert reviews == []


async def test_search_divides_budget_by_products_not_search_page(mock_client):
    # 50 reviews across 5 products should ask ~10 per product, not 50 // 40 = 1.
    adapter = AmazonReviewAdapter(max_reviews=50, max_products=5, client=mock_client)
    adapter._search_products = AsyncMock(return_value=[f"B{i:09d}" for i in range(40)])

    captured_limits: list[int | None] = []

    async def fake_collect_reviews(asin, limit=None):
        captured_limits.append(limit)
        return []

    adapter._collect_reviews = fake_collect_reviews

    await adapter.collect("search:widgets")

    assert len(captured_limits) == 5           # only max_products visited
    assert all(limit == 10 for limit in captured_limits)


def test_parse_reviews_id_before_data_hook():
    # Live Amazon markup puts id before data-hook; parsing must be
    # attribute-order-independent.
    html = """
    <div id="R9ZZZ999" data-hook="review" class="review">
        <span data-hook="review-star-rating"><span>1.0 out of 5 stars</span></span>
        <a data-hook="review-title"><span>Broke immediately</span></a>
        <span class="a-profile-name">Sam Buyer</span>
        <span data-hook="review-body"><span>Stopped working on day one.</span></span>
    </div>
    """
    reviews = _parse_reviews(html, "B08TEST123")
    assert len(reviews) == 1
    assert reviews[0].external_id == "R9ZZZ999"
    assert reviews[0].metadata["star_rating"] == 1.0
    assert "Broke immediately" in reviews[0].text


# ── collect by ASIN ─────────────────────────────────────────────────


async def test_collect_by_asin(mock_client):
    adapter = AmazonReviewAdapter(max_reviews=10, client=mock_client)

    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_resp(SAMPLE_REVIEW_HTML)
        return _mock_resp("<html>no more</html>")

    mock_client.get = mock_get

    results = await adapter.collect("asin:B08N5WRWNW")

    assert len(results) == 2
    assert all(r.content_type == "review" for r in results)
    assert results[0].metadata["asin"] == "B08N5WRWNW"


# ── collect by search ───────────────────────────────────────────────


async def test_collect_by_search(mock_client):
    adapter = AmazonReviewAdapter(max_reviews=10, max_products=2, client=mock_client)

    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if "/s" in str(path):
            return _mock_resp(SAMPLE_SEARCH_HTML)
        if call_count <= 3:
            return _mock_resp(SAMPLE_REVIEW_HTML)
        return _mock_resp("<html>empty</html>")

    mock_client.get = mock_get

    results = await adapter.collect("search:wireless earbuds")

    assert len(results) > 0
    assert all(r.content_type == "review" for r in results)


# ── bare query defaults to search ──────────────────────────────────


async def test_bare_query_defaults_to_search(mock_client):
    adapter = AmazonReviewAdapter(max_reviews=5, max_products=1, client=mock_client)

    async def mock_get(path, **kwargs):
        if "/s" in str(path):
            return _mock_resp(SAMPLE_SEARCH_HTML)
        return _mock_resp(SAMPLE_REVIEW_HTML)

    mock_client.get = mock_get

    results = await adapter.collect("wireless earbuds")
    assert len(results) > 0


# ── max_reviews respected ──────────────────────────────────────────


async def test_max_reviews_cap(mock_client):
    adapter = AmazonReviewAdapter(max_reviews=1, client=mock_client)

    async def mock_get(path, **kwargs):
        return _mock_resp(SAMPLE_REVIEW_HTML)

    mock_client.get = mock_get

    results = await adapter.collect("asin:B08TEST")
    assert len(results) <= 1


# ── empty results ──────────────────────────────────────────────────


async def test_empty_results(mock_client):
    adapter = AmazonReviewAdapter(client=mock_client)
    mock_client.get = AsyncMock(return_value=_mock_resp("<html>nothing</html>"))

    results = await adapter.collect("asin:B00NONEXIST")
    assert results == []


# ── pagination is bounded even when Amazon never returns empty ─────


async def test_pagination_stops_after_max_pages(mock_client):
    """Amazon has been observed to repeat the last valid page past its real
    pagination limit instead of returning empty — without an explicit page
    cap the collector would retry forever."""
    adapter = AmazonReviewAdapter(
        max_reviews=10_000, client=mock_client, request_interval_seconds=0.0
    )

    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        return _mock_resp(SAMPLE_REVIEW_HTML)  # never empty, always 2 reviews

    mock_client.get = mock_get

    results = await adapter.collect("asin:B08TEST")

    assert call_count == MAX_REVIEW_PAGES
    assert len(results) == MAX_REVIEW_PAGES * 2


# ── request counting ──────────────────────────────────────────────


async def test_request_count(mock_client):
    adapter = AmazonReviewAdapter(client=mock_client)

    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_resp(SAMPLE_REVIEW_HTML)
        return _mock_resp("<html>empty</html>")

    mock_client.get = mock_get

    await adapter.collect("asin:B08TEST")
    assert adapter.request_count >= 1


# ── star filter ────────────────────────────────────────────────────


FIVE_STAR_REVIEW_HTML = """
<div data-hook="review" id="R5GOOD999">
    <span data-hook="review-star-rating"><span>5.0 out of 5 stars</span></span>
    <a data-hook="review-title"><span>Love it</span></a>
    <span class="a-profile-name">Happy Buyer</span>
    <span data-hook="review-body"><span>Works perfectly.</span></span>
</div>
"""


async def test_star_filter_uses_amazon_critical_bucket_and_drops_high_ratings(mock_client):
    # "1,2,3" is not a value Amazon recognises; it silently returns every
    # rating. "critical" is Amazon's own 1-3 star bucket.
    assert STAR_FILTER == "critical"
    adapter = AmazonReviewAdapter(max_reviews=10, client=mock_client)

    captured_params: list[dict] = []
    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        captured_params.append(kwargs.get("params") or {})
        if call_count == 1:
            return _mock_resp(SAMPLE_REVIEW_HTML + FIVE_STAR_REVIEW_HTML)
        return _mock_resp("<html>no more</html>")

    mock_client.get = mock_get

    results = await adapter.collect("asin:B08N5WRWNW")

    assert captured_params[0]["filterByStar"] == "critical"
    # Even if Amazon ignores the filter, 4-5 star reviews never leak through.
    assert [r.external_id for r in results] == ["R1ABC123", "R2DEF456"]
    assert all(r.metadata["star_rating"] <= 3 for r in results)


async def test_implements_dissatisfaction_provider(monkeypatch):
    """CORP1 Stage 4/5, T2: Amazon Reviews is DissatisfactionProvider, delegating to collect()."""
    from corp.workers.providers.capabilities import DissatisfactionProvider

    adapter = AmazonReviewAdapter()
    assert isinstance(adapter, DissatisfactionProvider)

    sentinel: list[object] = []
    calls: list[str] = []

    async def fake_collect(identifier: str) -> list[object]:
        calls.append(identifier)
        return sentinel

    monkeypatch.setattr(adapter, "collect", fake_collect)

    assert await adapter.fetch_dissatisfaction("search:espresso machine") is sentinel
    assert calls == ["search:espresso machine"]
