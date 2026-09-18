"""Wikipedia adapter — Wikimedia Pageviews + Search APIs, fully open.

Wikipedia pageview data is a strong demand-validation signal: articles
with sustained high traffic indicate persistent audience interest in
a topic. The search API surfaces relevant articles; the pageviews API
quantifies interest.

Identifier forms accepted by :meth:`collect`:

* ``article:Python_(programming_language)`` — pageviews for a specific article.
* bare ``keyword`` — searches Wikipedia, then fetches pageviews for top results.

Requires a descriptive User-Agent header per Wikimedia policy.

API documentation:
* https://www.mediawiki.org/wiki/API:Search
* https://wikimedia.org/api/rest_v1/#/Pageviews_data
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
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
from corp.workers.providers.capabilities import TrendProvider

logger = logging.getLogger(__name__)

WIKI_API_TEMPLATE = "https://{language}.wikipedia.org/w/api.php"
PAGEVIEWS_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
DEFAULT_USER_AGENT = "CORP-research/0.1 (creator opportunity research; https://github.com)"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, httpx.TransportError)


class WikipediaAdapter(SourceAdapter, TrendProvider):
    """Collects Wikipedia article summaries with pageview trend data.

    Each article becomes a ``pageview_trend`` content item. The metadata
    includes daily pageview counts, total views, and average daily views.
    """

    def __init__(
        self,
        max_articles: int = 10,
        pageview_days: int = 30,
        language: str = "en",
        user_agent: str = DEFAULT_USER_AGENT,
        request_interval_seconds: float = 1.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._max_articles = max_articles
        self._pageview_days = pageview_days
        self._language = language
        self._user_agent = user_agent
        self._interval = request_interval_seconds
        self._client = client
        self._last_request_at: float | None = None
        self.request_count = 0

    @property
    def _wiki_api(self) -> str:
        return WIKI_API_TEMPLATE.format(language=self._language)

    @property
    def platform(self) -> str:
        return "wikipedia"

    @property
    def family(self) -> AdapterFamily:
        return AdapterFamily.NICHE

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OFFICIAL

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        identifier = identifier.strip()
        if identifier.startswith("article:"):
            article = identifier[8:].strip()
            item = await self._collect_article(article)
            return [item] if item else []
        return await self._search_and_collect(identifier)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_trend(self, query: str) -> list[NormalizedContent]:
        """TrendProvider (CORP1 Stage 4/5, T2): sustained article pageviews
        are a demand-validation signal. Not in the CORP1 spec's original
        Phase 1.2 mapping table (a gap found while implementing T2 — the
        table covered 9 adapters + Web Presence but omitted this one);
        assigned here based on this adapter's own documented purpose.
        Delegates to collect() unchanged."""
        return await self.collect(query)

    async def _search_and_collect(self, query: str) -> list[NormalizedContent]:
        articles = await self._search_articles(query)
        results: list[NormalizedContent] = []
        for title in articles[: self._max_articles]:
            item = await self._collect_article(title)
            if item:
                results.append(item)
        return results

    async def _search_articles(self, query: str) -> list[str]:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": self._max_articles,
            "format": "json",
        }
        data = await self._get_json(self._wiki_api, params)
        return [
            r["title"]
            for r in data.get("query", {}).get("search", [])
        ]

    async def _collect_article(self, title: str) -> NormalizedContent | None:
        snippet = await self._get_extract(title)
        pageviews = await self._get_pageviews(title)

        daily = pageviews.get("daily", [])
        if not snippet and not daily:
            return None
        total = sum(d.get("views", 0) for d in daily)
        avg = total / max(len(daily), 1)

        text = snippet or title

        return NormalizedContent(
            source_platform="wikipedia",
            content_type="pageview_trend",
            external_id=f"wiki_{title.replace(' ', '_')}",
            text=text,
            author=None,
            timestamp=datetime.now(tz=UTC),
            url=f"https://{self._language}.wikipedia.org/wiki/{title.replace(' ', '_')}",
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "title": title,
                "language": self._language,
                "total_views": total,
                "avg_daily_views": round(avg, 1),
                "pageview_days": self._pageview_days,
                "daily_views": daily[-7:] if daily else [],
            },
        )

    async def _get_extract(self, title: str) -> str | None:
        params = {
            "action": "query",
            "titles": title,
            "prop": "extracts",
            "exintro": "true",
            "explaintext": "true",
            "exsentences": "3",
            "format": "json",
        }
        data = await self._get_json(self._wiki_api, params)
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            return page.get("extract", "")  # type: ignore[no-any-return]
        return None

    async def _get_pageviews(self, title: str) -> dict[str, Any]:
        end = datetime.now(tz=UTC)
        start = end - timedelta(days=self._pageview_days)
        article = title.replace(" ", "_")
        project = f"{self._language}.wikipedia"

        path = (
            f"{PAGEVIEWS_API}/{project}/all-access/all-agents"
            f"/{article}/daily/{start:%Y%m%d00}/{end:%Y%m%d00}"
        )
        try:
            data = await self._get_json(path, {})
            items = data.get("items", [])
            return {
                "daily": [
                    {"date": i.get("timestamp", "")[:8], "views": i.get("views", 0)}
                    for i in items
                ]
            }
        except Exception as exc:
            logger.warning("Pageviews fetch failed for %s: %s", title, exc)
            return {"daily": []}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": self._user_agent},
                timeout=15.0,
                follow_redirects=True,
            )
        return self._client

    async def _throttle(self) -> None:
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
        wait=wait_exponential(multiplier=2, min=2, max=30),
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
        return resp.json()  # type: ignore[no-any-return]
