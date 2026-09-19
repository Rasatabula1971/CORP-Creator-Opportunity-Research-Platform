"""Marketplace adapter — Gumroad, Etsy, Udemy public listings.

Product listings on digital marketplaces tell CORP what already sells in a
niche: saturation level, price points, and review sentiment. This is the
§8 competition/solution-research signal.

Identifier forms accepted by :meth:`collect`:

* ``gumroad:keyword`` — search Gumroad discover for products matching keyword.
* ``etsy:keyword`` — search Etsy for digital product listings.
* ``udemy:keyword`` — search Udemy for courses matching keyword.
* bare ``keyword`` — searches all three marketplaces.

Each listing becomes a ``listing`` content item with pricing, review count,
and rating in metadata. The adapter scrapes publicly accessible pages;
all three marketplaces serve their product listings as public HTML.

``ComplianceStatus.VERIFY`` — marketplace ToS may restrict automated access.
Evidence collected here should be verified for compliance before production.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

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
from corp.workers.providers.capabilities import SolutionProvider, TransactionProvider

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

MARKETPLACE_URLS = {
    "gumroad": "https://gumroad.com/discover",
    "etsy": "https://www.etsy.com/search",
    "udemy": "https://www.udemy.com/api-2.0/courses",
}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, httpx.TransportError)


class _TextExtractor(HTMLParser):
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


class MarketplaceAdapter(SourceAdapter, TransactionProvider, SolutionProvider):
    """Collects product listings from digital marketplaces as saturation signals.

    Each listing becomes a ``listing`` content item. The metadata includes
    price, rating, review count, and marketplace name.
    """

    def __init__(
        self,
        max_listings: int = 30,
        marketplaces: list[str] | None = None,
        request_interval_seconds: float = 2.0,
        client: httpx.AsyncClient | None = None,
        etsy_api_key: str | None = None,
    ) -> None:
        self._max_listings = max_listings
        self._marketplaces = marketplaces or ["gumroad", "etsy", "udemy"]
        self._interval = request_interval_seconds
        self._client = client
        self._etsy_api_key = etsy_api_key
        self._last_request_at: float | None = None
        self._throttle_lock = asyncio.Lock()
        self.request_count = 0

    @property
    def platform(self) -> str:
        return "marketplace"

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

        for prefix in ("gumroad:", "etsy:", "udemy:"):
            if identifier.startswith(prefix):
                marketplace = prefix[:-1]
                query = identifier[len(prefix):].strip()
                return await self._collect_from(marketplace, query)

        return await self._collect_all(identifier)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # ── Capability interfaces (CORP1 Stage 4/5, T2) ────────────────────
    # Both delegate to the same collect() unchanged — a marketplace
    # listing IS a transaction signal (people already pay) and IS a
    # solution signal (this is what's already competing), from the same
    # listing data.

    async def fetch_transactions(self, query: str) -> list[NormalizedContent]:
        return await self.collect(query)

    async def fetch_solutions(self, query: str) -> list[NormalizedContent]:
        return await self.collect(query)

    async def _collect_all(self, query: str) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        per_marketplace = max(1, self._max_listings // len(self._marketplaces))
        errors: list[tuple[str, Exception]] = []
        attempted = 0
        for marketplace in self._marketplaces:
            if len(results) >= self._max_listings:
                break
            attempted += 1
            try:
                items = await self._collect_from(marketplace, query, limit=per_marketplace)
            except Exception as exc:
                # Isolate marketplaces: one failing site (e.g. Udemy 403) must not
                # discard listings already gathered from the others.
                logger.warning("Marketplace %s failed for %r: %s", marketplace, query, exc)
                errors.append((marketplace, exc))
                continue
            for item in items:
                if len(results) >= self._max_listings:
                    break
                results.append(item)
        # Only surface a failure when every marketplace we tried errored and none
        # produced results — so the caller records the source as failed rather
        # than silently empty. A partial failure keeps whatever was collected.
        if errors and len(errors) == attempted and not results:
            summary = "; ".join(f"{m}: {e}" for m, e in errors)
            raise RuntimeError(f"All marketplaces failed for {query!r}: {summary}")
        return results

    async def _collect_from(
        self, marketplace: str, query: str, limit: int | None = None
    ) -> list[NormalizedContent]:
        limit = limit or self._max_listings
        if marketplace == "gumroad":
            return await self._collect_gumroad(query, limit)
        if marketplace == "etsy":
            return await self._collect_etsy(query, limit)
        if marketplace == "udemy":
            return await self._collect_udemy(query, limit)
        logger.warning("Unknown marketplace: %s", marketplace)
        return []

    async def _collect_gumroad(self, query: str, limit: int) -> list[NormalizedContent]:
        html = await self._get_page(
            MARKETPLACE_URLS["gumroad"],
            params={"query": query},
        )
        return _parse_gumroad_listings(html, query)[:limit]

    async def _collect_etsy(self, query: str, limit: int) -> list[NormalizedContent]:
        if self._etsy_api_key:
            return await self._collect_etsy_api(query, limit)
        html = await self._get_page(
            MARKETPLACE_URLS["etsy"],
            params={"q": query, "ref": "search_bar"},
        )
        return _parse_etsy_listings(html, query)[:limit]

    async def _collect_etsy_api(self, query: str, limit: int) -> list[NormalizedContent]:
        data = await self._get_json(
            "https://openapi.etsy.com/v3/application/listings/active",
            params={"keywords": query, "limit": min(limit, 25)},
            headers={"x-api-key": self._etsy_api_key or ""},
        )
        return _parse_etsy_api_response(data, query)[:limit]

    async def _collect_udemy(self, query: str, limit: int) -> list[NormalizedContent]:
        data = await self._get_json(
            MARKETPLACE_URLS["udemy"],
            params={
                "search": query,
                "page_size": min(limit, 20),
                "ordering": "relevance",
                "fields[course]": "title,headline,url,price,avg_rating,num_reviews,num_subscribers,visible_instructors",
            },
        )
        return _parse_udemy_response(data, query)[:limit]

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/json",
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
    async def _get_page(self, url: str, params: dict[str, str] | None = None) -> str:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(url, params=params)
        self.request_count += 1
        if resp.status_code == 429:
            logger.warning("Marketplace rate limit hit on %s", url)
        resp.raise_for_status()
        return resp.text

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=3, min=3, max=30),
        reraise=True,
    )
    async def _get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(url, params=params, headers=headers or {})
        self.request_count += 1
        if resp.status_code == 429:
            logger.warning("Marketplace rate limit hit on %s", url)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]


def _parse_gumroad_listings(html: str, query: str) -> list[NormalizedContent]:
    results: list[NormalizedContent] = []
    now = datetime.now(tz=UTC)

    blocks = re.findall(
        r'class="product-card"[^>]*>(.*?)(?=class="product-card"|$)',
        html,
        re.DOTALL,
    )

    for block in blocks:
        title_match = re.search(
            r'class="[^"]*product-card__title[^"]*"[^>]*>(.*?)</[^>]+>',
            block,
            re.DOTALL,
        )
        price_match = re.search(
            r'class="[^"]*price[^"]*"[^>]*>(.*?)</[^>]+>',
            block,
            re.DOTALL,
        )
        creator_match = re.search(
            r'class="[^"]*product-card__creator[^"]*"[^>]*>(.*?)</[^>]+>',
            block,
            re.DOTALL,
        )
        link_match = re.search(r'href="(https?://[^"]+)"', block)
        rating_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:star|★)', block, re.I)

        title = _html_to_text(title_match.group(1)) if title_match else ""
        if not title:
            continue

        price_text = _html_to_text(price_match.group(1)) if price_match else None
        price = _extract_price(price_text) if price_text else None
        creator = _html_to_text(creator_match.group(1)) if creator_match else None
        url = link_match.group(1) if link_match else None
        rating = float(rating_match.group(1)) if rating_match else None

        ext_id = stable_id("gm_", title, url)
        results.append(
            NormalizedContent(
                source_platform="marketplace",
                content_type="listing",
                external_id=ext_id,
                text=title,
                author=creator,
                timestamp=now,
                url=url,
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.VERIFY,
                metadata={
                    "marketplace": "gumroad",
                    "query": query,
                    "price": price,
                    "price_text": price_text,
                    "rating": rating,
                },
            )
        )

    return results


def _parse_etsy_listings(html: str, query: str) -> list[NormalizedContent]:
    results: list[NormalizedContent] = []
    now = datetime.now(tz=UTC)

    blocks = re.findall(
        r'data-listing-id="(\d+)"(.*?)(?=data-listing-id="|$)',
        html,
        re.DOTALL,
    )

    for listing_id, block in blocks:
        title_match = re.search(
            r'(?:alt|title)="([^"]{5,})"',
            block,
        )
        price_match = re.search(
            r'class="[^"]*price[^"]*"[^>]*>\s*\$?([\d,.]+)',
            block,
            re.I,
        )
        if not price_match:
            price_match = re.search(r'\$([\d,.]+)', block)
        shop_match = re.search(
            r'class="[^"]*shop-name[^"]*"[^>]*>(.*?)</[^>]+>',
            block,
            re.DOTALL,
        )
        rating_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:star|★)', block, re.I)
        review_count_match = re.search(r'\((\d[\d,]*)\s*(?:review|sale)', block, re.I)
        link_match = re.search(r'href="(https://www\.etsy\.com/listing/\d+[^"]*)"', block)

        title = _html_to_text(title_match.group(1)) if title_match else ""
        if not title:
            continue

        price = _extract_price(price_match.group(1)) if price_match else None
        shop = _html_to_text(shop_match.group(1)) if shop_match else None
        rating = float(rating_match.group(1)) if rating_match else None
        review_count = (
            int(review_count_match.group(1).replace(",", ""))
            if review_count_match
            else None
        )
        url = link_match.group(1) if link_match else None

        results.append(
            NormalizedContent(
                source_platform="marketplace",
                content_type="listing",
                external_id=f"etsy_{listing_id}",
                text=title,
                author=shop,
                timestamp=now,
                url=url,
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.VERIFY,
                metadata={
                    "marketplace": "etsy",
                    "query": query,
                    "price": price,
                    "rating": rating,
                    "review_count": review_count,
                },
            )
        )

    return results


def _parse_udemy_response(
    data: dict[str, Any], query: str
) -> list[NormalizedContent]:
    results: list[NormalizedContent] = []
    now = datetime.now(tz=UTC)

    for course in data.get("results", []):
        title = course.get("title", "")
        headline = course.get("headline", "")
        text = f"{title}\n\n{headline}".strip() if headline else title
        if not text:
            continue

        price_detail = course.get("price_detail") or course.get("price") or {}
        if isinstance(price_detail, dict):
            price = price_detail.get("amount")
            price_text = price_detail.get("price_string")
        elif isinstance(price_detail, str):
            price = _extract_price(price_detail)
            price_text = price_detail
        else:
            price = None
            price_text = None

        instructors = course.get("visible_instructors", [])
        instructor = instructors[0].get("display_name") if instructors else None

        course_id = course.get("id") or stable_id("", title)
        url_path = course.get("url", "")
        url = f"https://www.udemy.com{url_path}" if url_path else None

        results.append(
            NormalizedContent(
                source_platform="marketplace",
                content_type="listing",
                external_id=f"udemy_{course_id}",
                text=text,
                author=instructor,
                timestamp=now,
                url=url,
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.VERIFY,
                metadata={
                    "marketplace": "udemy",
                    "query": query,
                    "price": float(price) if price is not None else None,
                    "price_text": price_text,
                    "rating": course.get("avg_rating"),
                    "review_count": course.get("num_reviews"),
                    "subscriber_count": course.get("num_subscribers"),
                },
            )
        )

    return results


def _parse_etsy_api_response(
    data: dict[str, Any], query: str
) -> list[NormalizedContent]:
    results: list[NormalizedContent] = []
    now = datetime.now(tz=UTC)

    for item in data.get("results", []):
        title = item.get("title", "")
        description = item.get("description", "")
        text = f"{title}\n\n{description[:200]}".strip() if description else title
        if not text:
            continue

        price_raw = item.get("price", {})
        if isinstance(price_raw, dict):
            amount = price_raw.get("amount")
            divisor = price_raw.get("divisor", 100)
            price = amount / divisor if amount is not None else None
            currency = price_raw.get("currency_code", "USD")
        else:
            price = None
            currency = "USD"

        listing_id = item.get("listing_id") or stable_id("", title)

        results.append(
            NormalizedContent(
                source_platform="marketplace",
                content_type="listing",
                external_id=f"etsy_{listing_id}",
                text=title,
                author=item.get("shop_id"),
                timestamp=now,
                url=item.get("url") or f"https://www.etsy.com/listing/{listing_id}",
                access_method=AccessMethod.OFFICIAL,
                compliance_status=ComplianceStatus.COMPLIANT,
                metadata={
                    "marketplace": "etsy",
                    "query": query,
                    "price": price,
                    "currency": currency,
                    "rating": None,
                    "review_count": item.get("num_favorers"),
                    "views": item.get("views"),
                    "tags": item.get("tags", [])[:5],
                },
            )
        )

    return results


def _extract_price(text: str) -> float | None:
    match = re.search(r'\$?([\d,.]+)', text)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None
