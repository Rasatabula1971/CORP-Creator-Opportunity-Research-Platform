"""Hacker News adapter — Algolia Search API, fully open.

HN is a high-quality source of technical audience problems, product
launches (Show HN), and community sentiment. The Algolia API is
fully open with no key required, returning structured JSON.

Identifier forms accepted by :meth:`collect`:

* bare ``query text`` — searches stories (titles + URLs).
* ``comments:query`` — searches comments (direct audience problems).
* ``show:query`` — searches Show HN posts (product/competition signals).

API documentation: https://hn.algolia.com/api
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
    wait_exponential,
)

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import AdapterFamily, NormalizedContent, SourceAdapter
from corp.workers.providers.capabilities import ProblemProvider

logger = logging.getLogger(__name__)

HN_API_BASE = "https://hn.algolia.com/api/v1"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, httpx.TransportError)


class HackerNewsAdapter(SourceAdapter, ProblemProvider):
    """Collects stories and comments from Hacker News via Algolia API.

    Stories become ``story`` items; comments become ``comment`` items
    with parent_id pointing to the story. Metadata includes points,
    comment count, and HN-specific fields.
    """

    def __init__(
        self,
        max_items: int = 50,
        request_interval_seconds: float = 1.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._max_items = max_items
        self._interval = request_interval_seconds
        self._client = client
        self._last_request_at: float | None = None
        self.request_count = 0

    @property
    def platform(self) -> str:
        return "hackernews"

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
        if identifier.startswith("comments:"):
            return await self._search(identifier[9:].strip(), tags="comment")
        if identifier.startswith("show:"):
            return await self._search(identifier[5:].strip(), tags="show_hn")
        return await self._search(identifier, tags="story")

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_problems(self, query: str) -> list[NormalizedContent]:
        """ProblemProvider (CORP1 Stage 4/5, T2): delegates to collect()
        unchanged — comments/show-HN posts double as technical problem
        signals."""
        return await self.collect(query)

    async def _search(
        self, query: str, tags: str = "story"
    ) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        page = 0

        while len(results) < self._max_items:
            params: dict[str, Any] = {
                "query": query,
                "tags": tags,
                "hitsPerPage": min(self._max_items - len(results), 50),
                "page": page,
            }
            data = await self._get_json("/search", params)
            hits = data.get("hits", [])
            if not hits:
                break

            for hit in hits:
                item = self._hit_to_content(hit, tags)
                if item is not None:
                    results.append(item)
                    if len(results) >= self._max_items:
                        break

            if page >= data.get("nbPages", 1) - 1:
                break
            page += 1

        return results

    def _hit_to_content(
        self, hit: dict[str, Any], tag: str
    ) -> NormalizedContent | None:
        if tag == "comment":
            return self._comment_to_content(hit)
        return self._story_to_content(hit)

    def _story_to_content(self, hit: dict[str, Any]) -> NormalizedContent | None:
        title = hit.get("title", "")
        if not title:
            return None
        story_text = hit.get("story_text") or ""
        text = f"{title}\n\n{story_text}".strip() if story_text else title

        return NormalizedContent(
            source_platform="hackernews",
            content_type="story",
            external_id=str(hit.get("objectID", "")),
            text=text,
            author=hit.get("author"),
            timestamp=_parse_ts(hit.get("created_at_i")),
            url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "title": title,
                "like_count": hit.get("points", 0),
                "comment_count": hit.get("num_comments", 0),
                "story_url": hit.get("url"),
                "hn_url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
                "tags": hit.get("_tags", []),
            },
        )

    def _comment_to_content(self, hit: dict[str, Any]) -> NormalizedContent | None:
        text = hit.get("comment_text", "")
        if not text:
            return None
        import re
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean).strip()

        return NormalizedContent(
            source_platform="hackernews",
            content_type="comment",
            external_id=str(hit.get("objectID", "")),
            text=clean,
            author=hit.get("author"),
            timestamp=_parse_ts(hit.get("created_at_i")),
            url=f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
            parent_id=str(hit.get("story_id", "")),
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "story_title": hit.get("story_title"),
                "story_url": hit.get("story_url"),
                "like_count": hit.get("points"),
                "tags": hit.get("_tags", []),
            },
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=HN_API_BASE,
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
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _get_json(
        self, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(path, params=params)
        self.request_count += 1
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]


def _parse_ts(epoch: int | None) -> datetime | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC)
