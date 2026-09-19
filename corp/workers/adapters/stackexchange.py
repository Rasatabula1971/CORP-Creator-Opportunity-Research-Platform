"""Stack Exchange adapter — open API, no credentials required.

Stack Exchange questions *are* audience problems: "How do I X?" is a
direct signal of unmet need. This adapter targets the niche-discovery
pipeline, not creator-bound collection.

Identifier forms accepted by :meth:`collect`:

* ``tag:python`` — questions tagged with ``python``, newest first.
* ``tag:python;django`` — questions tagged with both ``python`` AND ``django``.
* bare ``query text`` — full-text search across all questions.

The API is throttled to 30 requests/second for anonymous clients (300
with an API key). This adapter stays well under that with a configurable
interval. Responses are gzip-compressed by default.

API documentation: https://api.stackexchange.com/docs
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

logger = logging.getLogger(__name__)

SE_API_BASE = "https://api.stackexchange.com/2.3"
DEFAULT_SITE = "stackoverflow"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, httpx.TransportError)


class StackExchangeAdapter(SourceAdapter):
    """Collects questions (and their answers) from a Stack Exchange site.

    Each question becomes a ``question`` content item; its accepted/top
    answer (if any) becomes a ``reply`` item parented to the question.
    """

    def __init__(
        self,
        site: str = DEFAULT_SITE,
        max_questions: int = 50,
        include_answers: bool = True,
        request_interval_seconds: float = 1.0,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._site = site
        self._max_questions = max_questions
        self._include_answers = include_answers
        self._interval = request_interval_seconds
        self._api_key = api_key
        self._client = client
        self._last_request_at: float | None = None
        self._throttle_lock = asyncio.Lock()
        self.request_count = 0
        self.quota_remaining: int | None = None

    @property
    def platform(self) -> str:
        return "stackexchange"

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
        if identifier.startswith("tag:"):
            return await self._collect_by_tag(identifier[4:])
        return await self._collect_by_search(identifier)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _collect_by_tag(self, tag_spec: str) -> list[NormalizedContent]:
        tags = tag_spec.replace(",", ";")
        params: dict[str, str | int] = {
            "tagged": tags,
            "sort": "activity",
            "order": "desc",
            "filter": "withbody",
        }
        return await self._fetch_questions(params)

    async def _collect_by_search(self, query: str) -> list[NormalizedContent]:
        params: dict[str, str | int] = {
            "intitle": query,
            "sort": "relevance",
            "order": "desc",
            "filter": "withbody",
        }
        return await self._fetch_questions(params)

    async def _fetch_questions(
        self, params: dict[str, str | int]
    ) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        page = 1
        remaining = self._max_questions

        while remaining > 0:
            page_params = {
                **params,
                "site": self._site,
                "pagesize": min(remaining, 100),
                "page": page,
            }
            if self._api_key:
                page_params["key"] = self._api_key

            data = await self._get_json("/questions", page_params)
            items = data.get("items", [])
            self.quota_remaining = data.get("quota_remaining")

            if not items:
                break

            for q in items:
                content = self._question_to_content(q)
                if content is not None:
                    results.append(content)
                remaining -= 1
                if remaining <= 0:
                    break

            if not data.get("has_more", False):
                break
            page += 1

        if self._include_answers and results:
            question_ids = [r.external_id for r in results]
            answers = await self._fetch_answers(question_ids)
            results.extend(answers)

        return results

    async def _fetch_answers(
        self, question_ids: list[str]
    ) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        for i in range(0, len(question_ids), 100):
            batch = question_ids[i : i + 100]
            ids = ";".join(batch)
            params: dict[str, str | int] = {
                "site": self._site,
                "sort": "votes",
                "order": "desc",
                "filter": "withbody",
                "pagesize": 100,
            }
            if self._api_key:
                params["key"] = self._api_key

            data = await self._get_json(f"/questions/{ids}/answers", params)
            for a in data.get("items", []):
                content = self._answer_to_content(a)
                if content is not None:
                    results.append(content)
        return results

    def _question_to_content(self, q: dict[str, Any]) -> NormalizedContent | None:
        question_id = q.get("question_id")
        if question_id is None:
            return None
        title = q.get("title", "")
        body = q.get("body", "")
        text = f"{title}\n\n{body}".strip() if body else title
        tags = q.get("tags", [])
        owner = q.get("owner", {})

        return NormalizedContent(
            source_platform="stackexchange",
            content_type="question",
            external_id=str(question_id),
            text=text,
            author=owner.get("display_name"),
            timestamp=_ts(q.get("creation_date")),
            url=q.get("link"),
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "title": title,
                "tags": tags,
                "view_count": q.get("view_count", 0),
                "like_count": q.get("score", 0),
                "comment_count": q.get("answer_count", 0),
                "is_answered": q.get("is_answered", False),
                "site": self._site,
            },
        )

    def _answer_to_content(self, a: dict[str, Any]) -> NormalizedContent | None:
        answer_id = a.get("answer_id")
        if answer_id is None:
            return None
        owner = a.get("owner", {})
        return NormalizedContent(
            source_platform="stackexchange",
            content_type="reply",
            external_id=str(answer_id),
            text=a.get("body", ""),
            author=owner.get("display_name"),
            timestamp=_ts(a.get("creation_date")),
            parent_id=str(a.get("question_id")),
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "like_count": a.get("score", 0),
                "is_accepted": a.get("is_accepted", False),
                "site": self._site,
            },
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=SE_API_BASE,
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
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _get_json(
        self, path: str, params: dict[str, str | int]
    ) -> dict[str, Any]:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(path, params=params)
        self.request_count += 1
        if resp.status_code == 429:
            logger.warning("Stack Exchange rate limit hit on %s", path)
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        if body.get("error_id"):
            logger.warning(
                "Stack Exchange API error %s: %s",
                body.get("error_id"),
                body.get("error_message"),
            )
        return body


def _ts(epoch: int | None) -> datetime | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC)
