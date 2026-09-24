"""Apple App Store adapter — review RSS + iTunes Search API.

Apple exposes a public RSS feed for app reviews and a search API for
finding apps by keyword. Both are fully open, no key required. The
RSS feed has been publicly available for years with no access restrictions.

App reviews are a strong unmet-need signal: "This app doesn't do X"
maps directly to audience problems in the mobile/software niche.

Identifier forms accepted by :meth:`collect`:

* ``id:123456789`` — reviews for a specific app by its App Store ID.
* ``search:keyword`` — searches iTunes for apps, then collects reviews
  from the top results.
* bare ``keyword`` — defaults to search mode.

API documentation:
* Reviews: https://itunes.apple.com/rss/customerreviews/id={id}/json
* Search: https://itunes.apple.com/search
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
)

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import (
    AdapterFamily,
    NormalizedContent,
    SourceAdapter,
    check_response_size,
    wait_with_retry_after,
)
from corp.workers.adapters.ids import stable_id
from corp.workers.providers.capabilities import DissatisfactionProvider, SolutionProvider

logger = logging.getLogger(__name__)

ITUNES_SEARCH = "https://itunes.apple.com/search"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
REVIEWS_RSS = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "id={app_id}/sortBy=mostRecent/json"
)

# Audit fix: fetch_dissatisfaction() must not count a 5-star review as
# dissatisfaction evidence. 1-3 stars is the conventional "not satisfied"
# cutoff for app-store ratings; configurable per adapter instance.
DEFAULT_DISSATISFACTION_MAX_STARS = 3


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, httpx.TransportError)


class AppStoreAdapter(SourceAdapter, SolutionProvider, DissatisfactionProvider):
    """Collects app reviews from Apple's App Store via RSS feed.

    Each review becomes a ``review`` content item. Metadata includes
    star rating, app name, app ID, and review title.
    """

    def __init__(
        self,
        max_reviews: int = 50,
        max_apps: int = 5,
        country: str = "us",
        request_interval_seconds: float = 1.0,
        client: httpx.AsyncClient | None = None,
        dissatisfaction_max_stars: int = DEFAULT_DISSATISFACTION_MAX_STARS,
    ) -> None:
        self._max_reviews = max_reviews
        self._max_apps = max_apps
        self._country = country
        self._interval = request_interval_seconds
        self._client = client
        self._dissatisfaction_max_stars = dissatisfaction_max_stars
        self._last_request_at: float | None = None
        self._throttle_lock = asyncio.Lock()
        self.request_count = 0
        # Single-flight per search term. The niche pipeline calls
        # fetch_solutions() and fetch_dissatisfaction() for the same query
        # on the same adapter instance (one call per capability), and both
        # start with the identical iTunes search -- so every niche cost two
        # search requests for one result set, and two throttle intervals.
        # Holding the in-flight Task (not just its result) lets concurrent
        # callers await the same request instead of each starting their
        # own; the same pattern as MarketplaceAdapter._collect_tasks.
        self._search_tasks: dict[str, asyncio.Task[list[dict[str, Any]]]] = {}

    @property
    def platform(self) -> str:
        return "appstore"

    @property
    def family(self) -> AdapterFamily:
        return AdapterFamily.NICHE

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        identifier = identifier.strip()
        if identifier.startswith("id:"):
            app_id = identifier[3:].strip()
            return await self._collect_reviews(app_id)
        query = identifier
        if query.startswith("search:"):
            query = query[7:].strip()
        return await self._collect_by_search(query)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # ── Capability interfaces (CORP1 Stage 4/5, T2) ────────────────────
    # These must NOT both delegate to collect(): that would turn every
    # review of one app into a distinct "solution" (ten reviews looks like
    # ten competitors) and let a 5-star review count as dissatisfaction.
    # fetch_solutions returns one item per app (the competitive landscape);
    # fetch_dissatisfaction returns only reviews at or below the configured
    # star-rating threshold.

    async def fetch_solutions(self, query: str) -> list[NormalizedContent]:
        """One NormalizedContent per app found for `query` — the existing
        solutions themselves, not their individual reviews."""
        query = query.strip()
        if query.startswith("id:"):
            app_id = query[3:].strip()
            app = await self._lookup_app(app_id)
            return [_parse_app_result(app)] if app else []
        search_query = query[7:].strip() if query.startswith("search:") else query
        results = await self._search_apps_raw(search_query)
        return [_parse_app_result(a) for a in results if "trackId" in a]

    async def fetch_dissatisfaction(self, query: str) -> list[NormalizedContent]:
        """Reviews at or below ``dissatisfaction_max_stars`` only. An
        unparseable rating can't be confirmed as dissatisfaction, so it is
        excluded rather than assumed."""
        reviews = await self.collect(query)
        return [
            r
            for r in reviews
            if (rating := r.metadata.get("star_rating")) is not None
            and rating <= self._dissatisfaction_max_stars
        ]

    async def _collect_by_search(self, query: str) -> list[NormalizedContent]:
        app_ids = await self._search_apps(query)
        results: list[NormalizedContent] = []
        per_app = max(1, self._max_reviews // max(1, len(app_ids)))
        for app_id in app_ids[: self._max_apps]:
            if len(results) >= self._max_reviews:
                break
            reviews = await self._collect_reviews(app_id, limit=per_app)
            for r in reviews:
                if len(results) >= self._max_reviews:
                    break
                results.append(r)
        return results

    async def _search_apps(self, query: str) -> list[str]:
        results = await self._search_apps_raw(query)
        return [str(r["trackId"]) for r in results if "trackId" in r]

    async def _search_apps_raw(self, query: str) -> list[dict[str, Any]]:
        key = query.strip().casefold()
        task = self._search_tasks.get(key)
        if task is None:
            task = asyncio.ensure_future(self._search_apps_uncached(query))
            self._search_tasks[key] = task
        try:
            return await task
        except BaseException:
            # A failed search is not a result to share: forget it so the
            # next caller (or the next pipeline run on this instance) gets
            # a fresh attempt rather than the cached exception.
            if self._search_tasks.get(key) is task:
                del self._search_tasks[key]
            raise

    async def _search_apps_uncached(self, query: str) -> list[dict[str, Any]]:
        params = {
            "term": query,
            "entity": "software",
            "limit": self._max_apps,
            "country": self._country,
        }
        data = await self._get_json(ITUNES_SEARCH, params)
        return data.get("results", [])  # type: ignore[no-any-return]

    async def _lookup_app(self, app_id: str) -> dict[str, Any] | None:
        data = await self._get_json(ITUNES_LOOKUP, {"id": app_id, "country": self._country})
        results = data.get("results", [])
        return results[0] if results else None

    async def _collect_reviews(
        self, app_id: str, limit: int | None = None
    ) -> list[NormalizedContent]:
        limit = limit or self._max_reviews
        url = REVIEWS_RSS.format(app_id=app_id, country=self._country)
        data = await self._get_json(url, {})
        return _parse_review_feed(data, app_id)[:limit]

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
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
        wait=wait_with_retry_after(multiplier=2, minimum=2, maximum=30),
        reraise=True,
    )
    async def _get_json(
        self, url: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(url, params=params)
        self.request_count += 1
        resp.raise_for_status()
        check_response_size(resp, "appstore")
        return resp.json()  # type: ignore[no-any-return]


def _parse_app_result(app: dict[str, Any]) -> NormalizedContent:
    """One iTunes Search/Lookup result → one SOLUTION evidence item: the
    app itself, not any of its reviews."""
    app_id = str(app.get("trackId", ""))
    name = app.get("trackName", "")
    description = (app.get("description") or "")[:500]
    text = f"{name}\n\n{description}".strip() if description else name

    seller = app.get("sellerName") or app.get("artistName")
    release = app.get("currentVersionReleaseDate") or app.get("releaseDate")
    timestamp = _parse_iso(release) or datetime.now(tz=UTC)

    return NormalizedContent(
        source_platform="appstore",
        content_type="app_listing",
        external_id=f"app_{app_id}" if app_id else stable_id("app_", name),
        text=text,
        author=seller,
        timestamp=timestamp,
        url=app.get("trackViewUrl"),
        access_method=AccessMethod.OPEN,
        compliance_status=ComplianceStatus.COMPLIANT,
        metadata={
            "app_id": app_id,
            "app_name": name,
            "price": app.get("price"),
            "formatted_price": app.get("formattedPrice"),
            "average_rating": app.get("averageUserRating"),
            "rating_count": app.get("userRatingCount"),
            "seller": seller,
        },
    )


def _parse_review_feed(
    data: dict[str, Any], app_id: str
) -> list[NormalizedContent]:
    results: list[NormalizedContent] = []
    feed = data.get("feed", {})
    entries = feed.get("entry", [])

    if isinstance(entries, dict):
        entries = [entries]

    for entry in entries:
        if "im:rating" not in entry:
            continue

        title_data = entry.get("title", {})
        title = title_data.get("label", "") if isinstance(title_data, dict) else str(title_data)

        content_data = entry.get("content", {})
        body = (
            content_data.get("label", "") if isinstance(content_data, dict) else str(content_data)
        )

        text = f"{title}\n\n{body}".strip() if body else title
        if not text:
            continue

        rating_data = entry.get("im:rating", {})
        rating = rating_data.get("label") if isinstance(rating_data, dict) else str(rating_data)
        try:
            star_rating = int(rating) if rating else None
        except (ValueError, TypeError):
            star_rating = None

        author_data = entry.get("author", {})
        author_name = author_data.get("name", {})
        if isinstance(author_name, dict):
            author = author_name.get("label")
        else:
            author = str(author_name) if author_name else None

        review_id_data = entry.get("id", {})
        review_id = (
            review_id_data.get("label", "")
            if isinstance(review_id_data, dict)
            else str(review_id_data)
        )
        ext_id = f"as_{review_id}" if review_id else stable_id("as_", text)

        link_data = entry.get("link", {})
        url = None
        if isinstance(link_data, dict):
            url = link_data.get("attributes", {}).get("href")
        elif isinstance(link_data, list) and link_data:
            url = link_data[0].get("attributes", {}).get("href")

        app_name_data = entry.get("im:name", {})
        app_name = app_name_data.get("label") if isinstance(app_name_data, dict) else None

        updated_data = entry.get("updated", {})
        updated = updated_data.get("label") if isinstance(updated_data, dict) else None
        timestamp = _parse_iso(updated) or datetime.now(tz=UTC)

        results.append(
            NormalizedContent(
                source_platform="appstore",
                content_type="review",
                external_id=ext_id,
                text=text,
                author=author,
                timestamp=timestamp,
                url=url,
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.COMPLIANT,
                metadata={
                    "app_id": app_id,
                    "app_name": app_name,
                    "title": title,
                    "star_rating": star_rating,
                },
            )
        )

    return results


def _parse_iso(text: str | None) -> datetime | None:
    """Parse an Apple RSS ``updated`` timestamp (ISO 8601), normalized to UTC."""
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
