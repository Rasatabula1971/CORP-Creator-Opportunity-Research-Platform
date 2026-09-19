"""Amazon review adapter — 1-3 star reviews as unmet-need signals.

Low-star Amazon reviews are a high-quality source of audience problems:
"This product doesn't do X" is a direct signal of unmet need and
competitor weakness.

Identifier forms accepted by :meth:`collect`:

* ``asin:B08N5WRWNW`` — reviews for a specific product ASIN.
* ``search:keyword`` — searches Amazon for products matching the keyword,
  then collects reviews from the top results.

This adapter scrapes publicly accessible review pages. Amazon product
pages and reviews are publicly visible without authentication. The adapter
uses a respectful throttle interval and identifies itself properly.

``ComplianceStatus.VERIFY`` — Amazon's Conditions of Use restrict automated
access. Evidence collected here should be verified for compliance before
use in production.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime
from html.parser import HTMLParser

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import AdapterFamily, NormalizedContent, SourceAdapter
from corp.workers.adapters.ids import stable_id
from corp.workers.providers.capabilities import DissatisfactionProvider

logger = logging.getLogger(__name__)

AMAZON_BASE = "https://www.amazon.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Amazon's own 1-3 star bucket. Other accepted values: one_star..five_star,
# positive, all_stars. Anything else (e.g. "1,2,3") is silently ignored and
# every rating comes back.
STAR_FILTER = "critical"

# Amazon caps how far its review pagination actually goes for anonymous
# access; past that it has been observed to repeat the last valid page
# instead of returning empty, which would otherwise loop forever below.
MAX_REVIEW_PAGES = 10


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, httpx.TransportError)


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text extractor."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._parts)).strip()


def _html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.get_text()


class AmazonReviewAdapter(SourceAdapter, DissatisfactionProvider):
    """Collects low-star Amazon reviews as unmet-need signals.

    Each review becomes a ``review`` content item. The metadata includes
    star rating, product ASIN, and review title. Only 1-3 star reviews
    are collected — these contain the strongest problem signals.
    """

    def __init__(
        self,
        max_reviews: int = 50,
        max_products: int = 5,
        star_filter: str = STAR_FILTER,
        request_interval_seconds: float = 3.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._max_reviews = max_reviews
        self._max_products = max_products
        self._star_filter = star_filter
        self._interval = request_interval_seconds
        self._client = client
        self._last_request_at: float | None = None
        self._throttle_lock = asyncio.Lock()
        self.request_count = 0

    @property
    def platform(self) -> str:
        return "amazon_reviews"

    @property
    def family(self) -> AdapterFamily:
        return AdapterFamily.NICHE

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.VERIFY

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        identifier = identifier.strip()
        if identifier.startswith("asin:"):
            asin = identifier[5:].strip().upper()
            return await self._collect_reviews(asin)
        if identifier.startswith("search:"):
            query = identifier[7:].strip()
            return await self._collect_by_search(query)
        return await self._collect_by_search(identifier)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_dissatisfaction(self, query: str) -> list[NormalizedContent]:
        """DissatisfactionProvider (CORP1 Stage 4/5, T2): 1-3 star reviews
        are a direct unmet-need signal. Delegates to collect() unchanged."""
        return await self.collect(query)

    async def _collect_by_search(self, query: str) -> list[NormalizedContent]:
        asins = await self._search_products(query)
        results: list[NormalizedContent] = []
        # Divide the budget across the products we actually visit, not the whole
        # search page (~40-60 ASINs) — otherwise per_product collapsed to 1 and a
        # max_reviews=50 / max_products=5 run returned ~5 reviews instead of 50.
        products = asins[: self._max_products]
        per_product = max(1, self._max_reviews // max(1, len(products)))
        for asin in products:
            if len(results) >= self._max_reviews:
                break
            reviews = await self._collect_reviews(asin, limit=per_product)
            for r in reviews:
                if len(results) >= self._max_reviews:
                    break
                results.append(r)
        return results

    async def _search_products(self, query: str) -> list[str]:
        html = await self._get_page("/s", params={"k": query, "ref": "nb_sb_noss"})
        return _extract_asins(html)

    async def _collect_reviews(
        self, asin: str, limit: int | None = None
    ) -> list[NormalizedContent]:
        limit = limit or self._max_reviews
        results: list[NormalizedContent] = []
        page = 1

        while len(results) < limit and page <= MAX_REVIEW_PAGES:
            html = await self._get_page(
                f"/product-reviews/{asin}",
                params={
                    "filterByStar": self._star_filter,
                    "pageNumber": str(page),
                    "sortBy": "recent",
                },
            )
            reviews = _parse_reviews(html, asin)
            if not reviews:
                break
            for r in reviews:
                if len(results) >= limit:
                    break
                # Amazon sometimes ignores the filter; never let 4-5 star
                # reviews through when we promised critical ones.
                stars = r.metadata.get("star_rating")
                if self._star_filter == STAR_FILTER and stars is not None and stars > 3:
                    continue
                results.append(r)
            page += 1

        return results

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=AMAZON_BASE,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    async def _throttle(self) -> None:
        # Locked so concurrent calls on the same adapter instance can't both
        # read a stale _last_request_at and fire back-to-back, defeating the
        # rate limit this method exists to enforce.
        async with self._throttle_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._last_request_at is not None:
                wait = self._interval - (now - self._last_request_at)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_request_at = loop.time()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=3, min=3, max=30),
        reraise=True,
    )
    async def _get_page(
        self, path: str, params: dict[str, str] | None = None
    ) -> str:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(path, params=params)
        self.request_count += 1
        if resp.status_code == 429:
            logger.warning("Amazon rate limit hit on %s", path)
        resp.raise_for_status()
        return resp.text


def _extract_asins(html: str) -> list[str]:
    """Pull ASINs from search results page HTML."""
    matches = re.findall(r'data-asin="([A-Z0-9]{10})"', html)
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        if m not in seen and m != "":
            seen.add(m)
            result.append(m)
    return result


def _parse_reviews(html: str, asin: str) -> list[NormalizedContent]:
    """Extract reviews from an Amazon product reviews page.

    Uses regex patterns against the known review page structure.
    This is deliberately simple — a full HTML parser would be more robust
    but heavier than needed for this niche-signal use case.
    """
    results: list[NormalizedContent] = []

    # Match each review div's opening tag regardless of attribute order — live
    # Amazon markup is <div id="R..." data-hook="review" ...> (id first), while
    # the previous pattern required data-hook before id and matched neither that
    # nor much else. Capture the id from the opening tag, then take the block
    # body up to the next review div.
    review_starts = list(
        re.finditer(r'<div\b[^>]*\bdata-hook="review"[^>]*>', html, re.DOTALL)
    )
    review_blocks: list[tuple[str, str]] = []
    for i, match in enumerate(review_starts):
        id_match = re.search(r'\bid="([^"]*)"', match.group(0))
        review_id = id_match.group(1) if id_match else ""
        end = review_starts[i + 1].start() if i + 1 < len(review_starts) else len(html)
        review_blocks.append((review_id, html[match.end():end]))

    for review_id, block in review_blocks:
        title_match = re.search(
            r'data-hook="review-title"[^>]*>.*?<span[^>]*>(.*?)</span>',
            block,
            re.DOTALL,
        )
        body_match = re.search(
            r'data-hook="review-body"[^>]*>.*?<span[^>]*>(.*?)</span>',
            block,
            re.DOTALL,
        )
        star_match = re.search(
            r'data-hook="review-star-rating"[^>]*>.*?(\d(?:\.\d)?)\s*out\s*of\s*5',
            block,
            re.DOTALL,
        )
        date_match = re.search(
            r'data-hook="review-date"[^>]*>(.*?)</span>',
            block,
            re.DOTALL,
        )
        author_match = re.search(
            r'<span class="a-profile-name"[^>]*>(.*?)</span>',
            block,
            re.DOTALL,
        )

        title = _html_to_text(title_match.group(1)) if title_match else ""
        body = _html_to_text(body_match.group(1)) if body_match else ""
        text = f"{title}\n\n{body}".strip() if body else title
        if not text:
            continue

        stars = float(star_match.group(1)) if star_match else None
        author = _html_to_text(author_match.group(1)) if author_match else None
        date_str = _html_to_text(date_match.group(1)) if date_match else None
        timestamp = _parse_review_date(date_str) if date_str else None

        ext_id = review_id or stable_id("amz_", text)

        results.append(
            NormalizedContent(
                source_platform="amazon_reviews",
                content_type="review",
                external_id=ext_id,
                text=text,
                author=author,
                timestamp=timestamp,
                url=f"{AMAZON_BASE}/product-reviews/{asin}",
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.VERIFY,
                metadata={
                    "asin": asin,
                    "title": title,
                    "star_rating": stars,
                    "star_filter": STAR_FILTER,
                },
            )
        )

    return results


def _parse_review_date(text: str) -> datetime | None:
    """Parse 'Reviewed in the United States on January 15, 2024' format."""
    match = re.search(
        r"on\s+(\w+)\s+(\d{1,2}),?\s+(\d{4})",
        text,
    )
    if not match:
        return None
    month_str, day_str, year_str = match.groups()
    months = {
        "January": 1, "February": 2, "March": 3, "April": 4,
        "May": 5, "June": 6, "July": 7, "August": 8,
        "September": 9, "October": 10, "November": 11, "December": 12,
    }
    month = months.get(month_str)
    if month is None:
        return None
    try:
        return datetime(int(year_str), month, int(day_str), tzinfo=UTC)
    except ValueError:
        return None
