"""Reddit adapter — public JSON feeds, no credentials, no paid services.

Reddit exposes every public listing and thread as JSON by appending ``.json``
to the URL. This adapter uses only those endpoints, identifies itself with a
descriptive User-Agent as Reddit's API rules require, and throttles itself to
the unauthenticated limit (roughly ten requests per minute).

Identifier forms accepted by :meth:`collect`:

* ``r/<subreddit>`` — a creator's own community; collects newest posts.
* ``u/<username>`` — a creator's profile; collects their newest submissions.
* bare ``<name>`` — treated as a subreddit.

Commercial use of Reddit's Data API requires Reddit's approval, so evidence is
tagged ``ComplianceStatus.VERIFY`` until that is confirmed.
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
    NormalizedContent,
    SourceAdapter,
    check_response_size,
    wait_with_retry_after,
)
from corp.workers.providers.capabilities import DissatisfactionProvider, ProblemProvider

logger = logging.getLogger(__name__)

REDDIT_BASE_URL = "https://www.reddit.com"
DEFAULT_USER_AGENT = "corp-research/0.1 (creator opportunity research; contact via GitHub)"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, httpx.TransportError)


class RedditAdapter(SourceAdapter, ProblemProvider, DissatisfactionProvider):
    """Collects posts and full comment trees from a subreddit or user profile."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        posts_per_creator: int = 25,
        request_interval_seconds: float = 6.0,
        max_comment_depth: int = 10,
        base_url: str = REDDIT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._posts_per_creator = posts_per_creator
        self._interval = request_interval_seconds
        self._max_depth = max_comment_depth
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._last_request_at: float | None = None
        self._throttle_lock = asyncio.Lock()
        self.request_count = 0

    # ── SourceAdapter contract ───────────────────────────────────────

    @property
    def platform(self) -> str:
        return "reddit"

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.VERIFY

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        posts = await self.list_posts(identifier)
        results: list[NormalizedContent] = list(posts)
        for post in posts:
            results.extend(await self.get_comments(post.external_id))
        return results

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # ── Capability interfaces (CORP1 Stage 4/5, T2) ────────────────────
    # Both delegate to the same collect() unchanged — Reddit posts and
    # comments are read through two different lenses (a stated problem,
    # or an expression of dissatisfaction with current solutions), not
    # two different collections.

    async def fetch_problems(self, query: str) -> list[NormalizedContent]:
        return await self.collect(query)

    async def fetch_dissatisfaction(self, query: str) -> list[NormalizedContent]:
        return await self.collect(query)

    # ── Listings ─────────────────────────────────────────────────────

    async def list_posts(self, identifier: str) -> list[NormalizedContent]:
        """Newest posts for ``r/<sub>``, ``u/<user>`` or a bare subreddit name."""
        path = self._listing_path(identifier)
        posts: list[NormalizedContent] = []
        after: str | None = None

        while len(posts) < self._posts_per_creator:
            params: dict[str, int | str] = {
                "limit": min(100, self._posts_per_creator - len(posts)),
                "raw_json": 1,
            }
            if after:
                params["after"] = after
            data = await self._get_json(path, params)
            if not isinstance(data, dict):
                break
            children = data.get("data", {}).get("children", [])
            for child in children:
                if child.get("kind") != "t3":
                    continue
                post = self._post_to_content(child["data"])
                if post is None:
                    continue
                posts.append(post)
                if len(posts) >= self._posts_per_creator:
                    break
            after = data.get("data", {}).get("after")
            if not after or not children:
                break

        return posts

    async def get_comments(self, post_id: str) -> list[NormalizedContent]:
        """Full comment tree for one post. Collapsed 'more' stubs are skipped."""
        data = await self._get_json(
            f"/comments/{post_id}.json",
            {"limit": 500, "depth": self._max_depth, "raw_json": 1, "sort": "top"},
        )
        if not isinstance(data, list) or len(data) < 2:
            return []
        results: list[NormalizedContent] = []
        self._walk_comments(data[1].get("data", {}).get("children", []), post_id, results)
        return results

    # ── Mapping ──────────────────────────────────────────────────────

    def _post_to_content(self, d: dict[str, Any]) -> NormalizedContent | None:
        post_id = d.get("id")
        if post_id is None:
            return None
        title = d.get("title") or ""
        body = d.get("selftext") or ""
        text = f"{title}\n\n{body}".strip() if body else title
        return NormalizedContent(
            source_platform="reddit",
            content_type="post",
            external_id=post_id,
            text=text,
            author=d.get("author"),
            timestamp=_ts(d.get("created_utc")),
            parent_id=None,
            url=f"{self._base_url}{d.get('permalink', '')}",
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "title": title,
                "description": body,
                "subreddit": d.get("subreddit"),
                "like_count": d.get("score", 0),
                "upvote_ratio": d.get("upvote_ratio"),
                "comment_count": d.get("num_comments", 0),
                "flair": d.get("link_flair_text"),
                "is_self": d.get("is_self", False),
            },
        )

    def _walk_comments(
        self, children: list[dict[str, Any]], post_id: str, out: list[NormalizedContent]
    ) -> None:
        for child in children:
            if child.get("kind") != "t1":
                continue  # "more" stubs need extra requests; skipped deliberately
            d = child["data"]
            comment_id = d.get("id")
            parent_full = d.get("parent_id", "")
            is_top_level = parent_full.startswith("t3_")
            if comment_id is not None:
                out.append(
                    NormalizedContent(
                        source_platform="reddit",
                        content_type="comment" if is_top_level else "reply",
                        external_id=comment_id,
                        text=d.get("body") or "",
                        author=d.get("author"),
                        timestamp=_ts(d.get("created_utc")),
                        parent_id=post_id if is_top_level else parent_full.split("_", 1)[-1],
                        url=f"{self._base_url}{d.get('permalink', '')}",
                        access_method=self.access_method,
                        compliance_status=self.compliance_status,
                        metadata={
                            "like_count": d.get("score", 0),
                            "depth": d.get("depth", 0),
                            "post_id": post_id,
                        },
                    )
                )
            replies = d.get("replies")
            if isinstance(replies, dict):
                self._walk_comments(replies.get("data", {}).get("children", []), post_id, out)

    @staticmethod
    def _listing_path(identifier: str) -> str:
        ident = identifier.strip().strip("/")
        if ident.startswith(("u/", "user/")):
            return f"/user/{ident.split('/', 1)[1]}/submitted.json"
        if ident.startswith("r/"):
            return f"/r/{ident[2:]}/new.json"
        return f"/r/{ident}/new.json"

    # ── HTTP ─────────────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"User-Agent": self._user_agent},
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
        wait=wait_with_retry_after(multiplier=5, minimum=5, maximum=60),
        reraise=True,
    )
    async def _get_json(
        self, path: str, params: dict[str, int | str]
    ) -> dict[str, Any] | list[Any]:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(path, params=params)
        self.request_count += 1
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            logger.warning("Reddit rate limit hit on %s (Retry-After=%s)", path, retry_after)
        resp.raise_for_status()
        check_response_size(resp, "reddit")
        body: dict[str, Any] | list[Any] = resp.json()
        return body


def _ts(created_utc: float | None) -> datetime | None:
    if created_utc is None:
        return None
    return datetime.fromtimestamp(float(created_utc), tz=UTC)
