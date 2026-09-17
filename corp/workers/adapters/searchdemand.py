"""Search-demand adapter — Google autocomplete as purchase-intent signal.

Google's autocomplete API is publicly accessible and returns real search
suggestions based on actual query volume. These suggestions reveal what
people are actively searching for in a niche, making them high-quality
purchase-intent signals.

Identifier forms accepted by :meth:`collect`:

* bare ``query text`` — fetches autocomplete suggestions for the query.
* ``related:query text`` — fetches suggestions for the query plus common
  purchase-intent modifiers ("best", "how to", "vs", "review", "alternative").

The autocomplete endpoint is free, public, and has no documented rate limit,
but this adapter throttles itself to avoid abuse. Responses are plain JSON.

No API key required. No ToS issues: the endpoint is publicly accessible
and returns only aggregate, non-personal data (popular search terms).
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
from corp.workers.adapters.ids import stable_id

logger = logging.getLogger(__name__)

AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search"

INTENT_MODIFIERS = [
    "best",
    "how to",
    "vs",
    "review",
    "alternative to",
    "tutorial",
    "course",
    "tool for",
]


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, httpx.TransportError)


class SearchDemandAdapter(SourceAdapter):
    """Collects Google autocomplete suggestions as search-demand signals.

    Each suggestion becomes a ``question`` content item whose text is the
    suggested query. The metadata includes the original seed query and the
    suggestion's rank position.
    """

    def __init__(
        self,
        max_suggestions: int = 50,
        language: str = "en",
        country: str = "us",
        request_interval_seconds: float = 1.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._max_suggestions = max_suggestions
        self._language = language
        self._country = country
        self._interval = request_interval_seconds
        self._client = client
        self._last_request_at: float | None = None
        self.request_count = 0

    @property
    def platform(self) -> str:
        return "searchdemand"

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
        if identifier.startswith("related:"):
            return await self._collect_with_modifiers(identifier[8:].strip())
        return await self._collect_base(identifier)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _collect_base(self, query: str) -> list[NormalizedContent]:
        suggestions = await self._fetch_suggestions(query)
        return self._to_content(query, suggestions)

    async def _collect_with_modifiers(self, query: str) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        seen: set[str] = set()

        base = await self._fetch_suggestions(query)
        for item in self._to_content(query, base):
            if item.text.lower() not in seen and len(results) < self._max_suggestions:
                seen.add(item.text.lower())
                results.append(item)

        for modifier in INTENT_MODIFIERS:
            if len(results) >= self._max_suggestions:
                break
            modified_query = f"{modifier} {query}"
            suggestions = await self._fetch_suggestions(modified_query)
            for item in self._to_content(modified_query, suggestions):
                if item.text.lower() not in seen and len(results) < self._max_suggestions:
                    seen.add(item.text.lower())
                    results.append(item)

        return results

    async def _fetch_suggestions(self, query: str) -> list[str]:
        params = {
            "client": "firefox",
            "q": query,
            "hl": self._language,
            "gl": self._country,
        }
        data = await self._get_json(params)
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
            return [str(s) for s in data[1] if isinstance(s, str)]
        return []

    def _to_content(
        self, seed_query: str, suggestions: list[str]
    ) -> list[NormalizedContent]:
        now = datetime.now(tz=UTC)
        results: list[NormalizedContent] = []
        for rank, suggestion in enumerate(suggestions):
            ext_id = stable_id("sd_", self._language, self._country, suggestion)
            results.append(
                NormalizedContent(
                    source_platform="searchdemand",
                    content_type="question",
                    external_id=ext_id,
                    text=suggestion,
                    author=None,
                    timestamp=now,
                    url=None,
                    access_method=self.access_method,
                    compliance_status=self.compliance_status,
                    metadata={
                        "seed_query": seed_query,
                        "rank": rank,
                        "language": self._language,
                        "country": self._country,
                    },
                )
            )
        return results

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
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
    async def _get_json(self, params: dict[str, str]) -> Any:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(AUTOCOMPLETE_URL, params=params)
        self.request_count += 1
        if resp.status_code == 429:
            logger.warning("Google autocomplete rate limit hit")
        resp.raise_for_status()
        return resp.json()
