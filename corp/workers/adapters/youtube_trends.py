"""YouTube trending as a momentum signal — official Data API v3 only.

Level 0 needs one thing from a trend source: given a broad catalogue topic
("woodworking", "personal finance"), how much momentum does it have right
now? This adapter answers that from YouTube's own trending charts through
the keyed, quota-metered Data API — no scraping, no undocumented endpoint.
That is the reason it exists alongside the Google Trends adapter: Google
Trends is reached through an RSS feed and pytrends, which the codebase
already labels "tolerated/undocumented"; this is licensed access.

How a pass spends quota
-----------------------
One chart pull, then local matching:

* ``videoCategories.list`` — 1 unit. Only *assignable* categories are kept
  (the rest are legacy labels YouTube no longer files videos under).
* ``videos.list(chart=mostPopular, videoCategoryId=…)`` — 1 unit per page,
  once per category.

That is roughly 15–30 units per refresh for a region, against a default
10,000/day key. Every catalogue topic is then scored against the cached
chart in memory. The alternative, ``search.list`` per topic, costs 100
units a call — about 5,800 units to score the shipped catalogue once —
and would starve creator onboarding, which draws on the same key.

Scoring
-------
A trending video matches a topic when every meaningful word of the topic
appears in the video's title or tags (whole words, light plural folding,
stopwords such as "and" ignored). Descriptions are deliberately not read:
they are where sponsor copy lives, and "sponsored by a personal finance
app" is not momentum for personal finance.

Matches are weighted by log views and saturate towards 100, so one viral
video cannot swamp several solid ones and the result sits on the same
0..100 scale ``TrendScanner`` already reads from ``avg_interest``. A topic
with no matching trending video returns no items rather than a zero: the
scanner then orders it by least-recently-researched, which is a better
tie-break among unmeasured topics than an arbitrary alphabetical one.

What it is not
--------------
Not a niche nominator. Trending on YouTube, as on Google, skews to music,
gaming and entertainment; this adapter only ranks topics the curated
catalogue already admits. It is also not wired into the drill engine's
evidence fan-out: that path builds a fresh adapter per keyword, so the
chart cache would not survive and a deep drill could spend thousands of
units in one pass.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import retry, retry_if_exception, stop_after_attempt

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import (
    AdapterFamily,
    NormalizedContent,
    SourceAdapter,
    wait_with_retry_after,
)
from corp.workers.adapters.ids import stable_id
from corp.workers.adapters.youtube import (
    _QUOTA_REASONS,
    QuotaExceededError,
    _http_error_reason,
    _is_retryable_http_error,
    _RateLimiter,
    describe_http_error,
)
from corp.workers.providers.capabilities import TrendProvider

logger = logging.getLogger(__name__)

# Raw log-view mass at which a topic reads ~63/100. Three matching videos at
# ~1M views each (≈41) land near 75; one at 100k views (≈11.5) near 32.
_SATURATION = 30.0

# Words that carry no topic meaning. "studying and productivity" must not
# require a trending video to contain the word "and".
_STOPWORDS = frozenset(
    {"a", "an", "and", "the", "of", "or", "for", "to", "in", "on", "with", "at", "by"}
)

_WORD = re.compile(r"[a-z0-9]+")

MOST_POPULAR_MAX_RESULTS = 50  # the API's per-page ceiling


def _fold(word: str) -> str:
    """Light plural folding: "games" → "game", "aquariums" → "aquarium".

    Deliberately not a stemmer. "running" stays "running" and "glass" stays
    "glass": a false match costs a wasted drill, a missed one only a later
    turn in the rotation.
    """
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _words(text: str) -> set[str]:
    return {_fold(w) for w in _WORD.findall(text.lower())}


def topic_terms(topic: str) -> frozenset[str]:
    """The words a video must contain to count toward ``topic``."""
    return frozenset(w for w in _words(topic) if w not in _STOPWORDS)


@dataclass(frozen=True, slots=True)
class ChartVideo:
    video_id: str
    title: str
    category_id: str
    category_title: str
    views: int
    words: frozenset[str]


class TrendChartUnavailableError(RuntimeError):
    """The chart could not be loaded; momentum is unavailable for now.

    Every load failure — quota, auth, network — surfaces as this, with a
    message that never contains the API key. Quota exhaustion is still an
    error here (never an empty chart), so it cannot pass for "no momentum".
    """


class YouTubeTrendsAdapter(SourceAdapter, TrendProvider):
    """``TrendProvider`` backed by YouTube's official trending charts."""

    def __init__(
        self,
        api_key: str,
        *,
        region: str = "US",
        daily_quota: int = 10_000,
        requests_per_second: int = 5,
        pages_per_category: int = 1,
        cache_ttl_seconds: float = 3600.0,
        failure_ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
        service: Any = None,
    ) -> None:
        # build() reads the discovery document bundled with the client
        # library; constructing the service makes no network call.
        self._service = service if service is not None else build(
            "youtube", "v3", developerKey=api_key
        )
        self._region = region.upper()
        self._limiter = _RateLimiter(requests_per_second)
        self._daily_quota = daily_quota
        self._quota_used = 0
        self._pages = max(1, pages_per_category)
        self._ttl = cache_ttl_seconds
        self._failure_ttl = failure_ttl_seconds
        self._clock = clock
        self._corpus: list[ChartVideo] | None = None
        self._loaded_at: float | None = None
        self._failed_at: float | None = None
        self._failure: str | None = None
        self._lock = asyncio.Lock()

    # ── SourceAdapter ────────────────────────────────────────────────

    @property
    def platform(self) -> str:
        return "youtube_trends"

    @property
    def family(self) -> AdapterFamily:
        return AdapterFamily.NICHE

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OFFICIAL

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    @property
    def region(self) -> str:
        return self._region

    @property
    def quota_used(self) -> int:
        return self._quota_used

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        """``chart`` returns the raw trending corpus (for inspection);
        anything else is treated as a topic and scored."""
        if identifier.strip().lower() == "chart":
            corpus = await self._ensure_corpus()
            return [self._video_item(v) for v in corpus]
        return await self.fetch_trend(identifier)

    async def close(self) -> None:
        self._corpus = None
        close = getattr(self._service, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 — releasing an HTTP pool
                logger.debug("YouTube trends: closing the API client failed", exc_info=True)

    # ── TrendProvider ────────────────────────────────────────────────

    async def fetch_trend(self, query: str) -> list[NormalizedContent]:
        terms = topic_terms(query)
        if not terms:
            return []
        corpus = await self._ensure_corpus()
        matches = [v for v in corpus if terms <= v.words]
        if not matches:
            return []

        matches.sort(key=lambda v: v.views, reverse=True)
        mass = sum(math.log1p(max(0, v.views)) for v in matches)
        score = round(100.0 * (1.0 - math.exp(-mass / _SATURATION)), 1)
        top = matches[0]
        return [
            NormalizedContent(
                source_platform="youtube",
                content_type="interest",
                external_id=stable_id("yt_chart_", query, self._region),
                text=(
                    f"YouTube trending ({self._region}): {len(matches)} video(s) "
                    f"match '{query}'"
                ),
                author=None,
                timestamp=datetime.now(tz=UTC),
                url=f"https://www.youtube.com/watch?v={top.video_id}",
                access_method=self.access_method,
                compliance_status=self.compliance_status,
                metadata={
                    "keyword": query,
                    "region": self._region,
                    # The key TrendScanner reads. Same 0..100 scale as the
                    # Google Trends interest series it replaces.
                    "avg_interest": score,
                    "matched_count": len(matches),
                    "chart_size": len(corpus),
                    "categories": sorted({v.category_title for v in matches}),
                    "matched_videos": [
                        {
                            "video_id": v.video_id,
                            "title": v.title,
                            "views": v.views,
                            "category": v.category_title,
                        }
                        for v in matches[:10]
                    ],
                    "source": "youtube_data_api_v3:videos.list(chart=mostPopular)",
                },
            )
        ]

    # ── Chart loading ────────────────────────────────────────────────

    async def _ensure_corpus(self) -> list[ChartVideo]:
        async with self._lock:
            now = self._clock()
            if (
                self._corpus is not None
                and self._loaded_at is not None
                and now - self._loaded_at < self._ttl
            ):
                return self._corpus
            # A failed load is remembered briefly. The scanner asks about
            # every catalogue topic in turn; without this, one outage would
            # become fifty-odd failing requests against the key.
            if self._failed_at is not None and now - self._failed_at < self._failure_ttl:
                raise TrendChartUnavailableError(
                    f"YouTube trending chart unavailable (cached failure): {self._failure}"
                )
            try:
                corpus = await asyncio.to_thread(self._load_chart)
            except Exception as exc:
                # Re-raised as our own error with a scrubbed message, and
                # `from None` so no traceback carries the original either:
                # str(HttpError) embeds the request URL, key=… and all, and
                # the scanner logs whatever this raises.
                self._failed_at = self._clock()
                self._failure = describe_http_error(exc)
                raise TrendChartUnavailableError(
                    f"YouTube trending chart unavailable: {self._failure}"
                ) from None
            self._corpus = corpus
            self._loaded_at = self._clock()
            self._failed_at = None
            self._failure = None
            logger.info(
                "YouTube trends: loaded %d trending video(s) for %s (%d quota units used)",
                len(corpus),
                self._region,
                self._quota_used,
            )
            return corpus

    @retry(
        retry=retry_if_exception(_is_retryable_http_error),
        stop=stop_after_attempt(3),
        wait=wait_with_retry_after(multiplier=1, minimum=2, maximum=30),
        reraise=True,
    )
    def _execute(self, request: Any, quota_cost: int = 1) -> dict[str, Any]:
        if self._quota_used + quota_cost > self._daily_quota:
            raise QuotaExceededError(
                f"Would exceed daily quota: {self._quota_used} + {quota_cost} "
                f"> {self._daily_quota}"
            )
        self._limiter.acquire()
        result = request.execute()
        self._quota_used += quota_cost
        return result  # type: ignore[no-any-return]

    def _load_chart(self) -> list[ChartVideo]:
        resp = self._execute(
            self._service.videoCategories().list(part="snippet", regionCode=self._region)
        )
        categories = [
            (str(item["id"]), str(item.get("snippet", {}).get("title", "")))
            for item in resp.get("items", [])
            if item.get("snippet", {}).get("assignable")
        ]
        if not categories:
            raise TrendChartUnavailableError(
                f"no assignable YouTube categories for region {self._region}"
            )

        seen: dict[str, ChartVideo] = {}
        for category_id, category_title in categories:
            page_token: str | None = None
            for _ in range(self._pages):
                params: dict[str, Any] = {
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "regionCode": self._region,
                    "videoCategoryId": category_id,
                    "maxResults": MOST_POPULAR_MAX_RESULTS,
                }
                if page_token:
                    params["pageToken"] = page_token
                try:
                    page = self._execute(self._service.videos().list(**params))
                except HttpError as exc:
                    if _http_error_reason(exc) in _QUOTA_REASONS:
                        raise  # systemic: stop spending, surface it
                    # Some assignable categories have no chart in some regions
                    # (videoChartNotFound). That is a fact about the category,
                    # not a failure of the pass.
                    logger.debug(
                        "YouTube trends: no chart for category %s (%s): %s",
                        category_id,
                        category_title,
                        describe_http_error(exc),
                    )
                    break
                for item in page.get("items", []):
                    video = _to_chart_video(item, category_id, category_title)
                    if video is not None and video.video_id not in seen:
                        seen[video.video_id] = video
                page_token = page.get("nextPageToken")
                if not page_token:
                    break
        return list(seen.values())

    def _video_item(self, video: ChartVideo) -> NormalizedContent:
        return NormalizedContent(
            source_platform="youtube",
            content_type="video",
            external_id=video.video_id,
            text=video.title,
            url=f"https://www.youtube.com/watch?v={video.video_id}",
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "view_count": video.views,
                "category_id": video.category_id,
                "category": video.category_title,
                "region": self._region,
                "chart": "mostPopular",
            },
        )


def _to_chart_video(
    item: dict[str, Any], category_id: str, category_title: str
) -> ChartVideo | None:
    video_id = item.get("id")
    if not isinstance(video_id, str) or not video_id:
        return None
    snippet = item.get("snippet", {}) or {}
    title = str(snippet.get("title", "") or "")
    tags = snippet.get("tags", []) or []
    try:
        views = int((item.get("statistics", {}) or {}).get("viewCount", 0) or 0)
    except (TypeError, ValueError):
        views = 0
    words = _words(title)
    for tag in tags:
        words |= _words(str(tag))
    return ChartVideo(
        video_id=video_id,
        title=title,
        category_id=category_id,
        category_title=category_title,
        views=views,
        words=frozenset(words),
    )
