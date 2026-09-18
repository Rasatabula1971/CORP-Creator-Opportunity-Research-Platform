"""YouTube Data API v3 adapter."""

import asyncio
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import NormalizedContent, SourceAdapter
from corp.workers.adapters.captions import fetch_youtube_caption

logger = logging.getLogger(__name__)

_ISO8601_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


def _parse_iso8601_duration(text: str) -> int | None:
    """Return the duration of an ISO 8601 string in seconds, or None if unparseable.

    YouTube reports every duration in this format (e.g. "PT4M13S" = 253s).
    """
    if not text:
        return None
    m = _ISO8601_DURATION_RE.match(text)
    if not m:
        return None
    parts = {k: int(v or 0) for k, v in m.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def _extract_channel_id(snippet: dict[str, Any]) -> str | None:
    """authorChannelId on a comment snippet is either {"value": "UCxx"} or absent."""
    channel = snippet.get("authorChannelId")
    if isinstance(channel, dict):
        return channel.get("value")
    if isinstance(channel, str):
        return channel
    return None


class QuotaExceededError(Exception):
    """Raised when YouTube API daily quota would be exceeded."""


def _is_retryable_http_error(exc: BaseException) -> bool:
    if not isinstance(exc, HttpError):
        return False
    return exc.resp.status in (429, 500, 502, 503, 504)


# YouTube returns HTTP 403 for both "comments are off for this video"
# (commentsDisabled) and quota/rate exhaustion. The first is a per-video fact to
# skip past; the rest are systemic and must not be swallowed as "no comments".
_QUOTA_REASONS = frozenset(
    {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"}
)


def _http_error_reason(exc: HttpError) -> str:
    """Best-effort first ``reason`` from a YouTube HttpError, or ""."""
    details = getattr(exc, "error_details", None)
    if details:
        for d in details:
            if isinstance(d, dict) and d.get("reason"):
                return str(d["reason"])
    try:
        import json

        content = getattr(exc, "content", None)
        payload = json.loads(content.decode("utf-8")) if content else {}
        errors = payload.get("error", {}).get("errors", [])
        if errors and isinstance(errors[0], dict):
            return str(errors[0].get("reason", ""))
    except Exception:
        pass
    return ""


class _RateLimiter:
    """Thread-safe per-second rate limiter."""

    def __init__(self, rps: int) -> None:
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._last_call = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()


class YouTubeAdapter(SourceAdapter):
    """Collects videos, comments, and captions from a YouTube channel."""

    def __init__(
        self,
        api_key: str,
        daily_quota: int = 10_000,
        requests_per_second: int = 5,
        max_videos: int = 50,
        max_comments_per_video: int = 100,
    ) -> None:
        self._service = build("youtube", "v3", developerKey=api_key)
        self._limiter = _RateLimiter(requests_per_second)
        self._quota_used = 0
        self._daily_quota = daily_quota
        self.max_videos = max_videos
        self.max_comments_per_video = max_comments_per_video

    @property
    def platform(self) -> str:
        return "youtube"

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OFFICIAL

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    @property
    def quota_used(self) -> int:
        return self._quota_used

    def _check_quota(self, cost: int) -> None:
        if self._quota_used + cost > self._daily_quota:
            raise QuotaExceededError(
                f"Would exceed daily quota: {self._quota_used} + {cost} > {self._daily_quota}"
            )

    @retry(
        retry=retry_if_exception(_is_retryable_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _execute(self, request: object, quota_cost: int = 1) -> dict[str, Any]:
        self._check_quota(quota_cost)
        self._limiter.acquire()
        result = request.execute()  # type: ignore[attr-defined]
        self._quota_used += quota_cost
        return result  # type: ignore[no-any-return]

    # ---- public API (all async, sync work dispatched to thread) ----

    async def resolve_channel(self, handle: str) -> str:
        """Resolve a channel handle (e.g. '@mkbhd') to a channel ID."""
        clean = handle.lstrip("@")

        def _resolve() -> str:
            req = self._service.channels().list(part="id", forHandle=clean)
            resp = self._execute(req, quota_cost=1)
            if resp.get("items"):
                return resp["items"][0]["id"]  # type: ignore[no-any-return]

            req = self._service.channels().list(part="id", forUsername=clean)
            resp = self._execute(req, quota_cost=1)
            if resp.get("items"):
                return resp["items"][0]["id"]  # type: ignore[no-any-return]

            raise ValueError(f"Channel not found: {handle}")

        return await asyncio.to_thread(_resolve)

    async def list_videos(
        self,
        channel_id: str,
        max_results: int | None = None,
        published_after: datetime | None = None,
    ) -> list[NormalizedContent]:
        """List videos from a channel's uploads playlist."""
        limit = max_results if max_results is not None else self.max_videos

        def _list() -> list[NormalizedContent]:
            req = self._service.channels().list(part="contentDetails", id=channel_id)
            ch_resp = self._execute(req, quota_cost=1)
            if not ch_resp.get("items"):
                return []
            uploads_id = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

            video_ids: list[str] = []
            snippets: dict[str, dict[str, Any]] = {}
            page_token: str | None = None
            remaining = limit

            while remaining > 0:
                kwargs: dict[str, Any] = {
                    "part": "snippet",
                    "playlistId": uploads_id,
                    "maxResults": min(remaining, 50),
                }
                if page_token:
                    kwargs["pageToken"] = page_token

                resp = self._execute(
                    self._service.playlistItems().list(**kwargs), quota_cost=1
                )

                for item in resp.get("items", []):
                    vid_id = item["snippet"]["resourceId"]["videoId"]
                    pub_at = item["snippet"].get("publishedAt")

                    if published_after and pub_at:
                        dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                        if dt < published_after:
                            remaining = 0
                            break

                    video_ids.append(vid_id)
                    snippets[vid_id] = item["snippet"]
                    remaining -= 1

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

            if not video_ids:
                return []

            # main-lineage tier-1 enrichment: pull snippet + contentDetails +
            # statistics in one batched call, so tags/language/duration/short
            # land on ContentItem without an extra fetch. Quota cost stays 1
            # per batch — parts don't multiply cost, only the id count does.
            stats: dict[str, dict[str, Any]] = {}
            details: dict[str, dict[str, Any]] = {}
            enriched_snippets: dict[str, dict[str, Any]] = {}
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i : i + 50]
                resp = self._execute(
                    self._service.videos().list(
                        part="statistics,contentDetails,snippet", id=",".join(batch)
                    ),
                    quota_cost=1,
                )
                for item in resp.get("items", []):
                    vid = item["id"]
                    stats[vid] = item.get("statistics", {})
                    details[vid] = item.get("contentDetails", {})
                    enriched_snippets[vid] = item.get("snippet", {})

            results: list[NormalizedContent] = []
            for vid_id in video_ids:
                snip = enriched_snippets.get(vid_id) or snippets[vid_id]
                st = stats.get(vid_id, {})
                cd = details.get(vid_id, {})
                pub = snip.get("publishedAt")
                ts = datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None
                duration_iso = cd.get("duration")
                duration_seconds = _parse_iso8601_duration(duration_iso) if duration_iso else None
                is_short = (
                    duration_seconds is not None and duration_seconds <= 60
                    if duration_seconds is not None
                    else None
                )

                results.append(
                    NormalizedContent(
                        source_platform="youtube",
                        content_type="video",
                        external_id=vid_id,
                        text=snip.get("title", ""),
                        author=snip.get("channelTitle"),
                        timestamp=ts,
                        url=f"https://www.youtube.com/watch?v={vid_id}",
                        access_method=self.access_method,
                        compliance_status=self.compliance_status,
                        metadata={
                            "description": snip.get("description", ""),
                            "view_count": int(st.get("viewCount", 0)),
                            "like_count": int(st.get("likeCount", 0)),
                            "comment_count": int(st.get("commentCount", 0)),
                            "channel_id": snip.get("channelId"),
                            # main-lineage typed enrichment (surfaces on ContentItem)
                            "duration": duration_seconds,
                            "tags": snip.get("tags") or [],
                            "language": snip.get("defaultAudioLanguage")
                            or snip.get("defaultLanguage"),
                            "is_short": is_short,
                            "definition": cd.get("definition"),
                        },
                    )
                )
            return results

        return await asyncio.to_thread(_list)

    async def get_comment_threads(
        self,
        video_id: str,
        max_results: int | None = None,
    ) -> list[NormalizedContent]:
        """Get comment threads (top-level + replies) for a video."""
        limit = max_results if max_results is not None else self.max_comments_per_video

        def _fetch() -> list[NormalizedContent]:
            results: list[NormalizedContent] = []
            page_token: str | None = None
            remaining = limit

            while remaining > 0:
                kwargs: dict[str, Any] = {
                    "part": "snippet,replies",
                    "videoId": video_id,
                    "maxResults": min(remaining, 100),
                    "textFormat": "plainText",
                }
                if page_token:
                    kwargs["pageToken"] = page_token

                try:
                    resp = self._execute(
                        self._service.commentThreads().list(**kwargs), quota_cost=1
                    )
                except HttpError as e:
                    if e.resp.status == 403:
                        reason = _http_error_reason(e)
                        if reason in _QUOTA_REASONS:
                            # Systemic — raising stops the run instead of silently
                            # returning zero comments for every remaining video.
                            raise QuotaExceededError(
                                f"YouTube quota/rate limit fetching comments ({reason})"
                            ) from e
                        logger.warning(
                            "No comments for video %s (403: %s)",
                            video_id,
                            reason or "commentsDisabled",
                        )
                        return results
                    raise

                for thread in resp.get("items", []):
                    top = thread["snippet"]["topLevelComment"]
                    top_snip = top["snippet"]
                    cid = top["id"]
                    pub = top_snip.get("publishedAt")
                    ts = datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None

                    results.append(
                        NormalizedContent(
                            source_platform="youtube",
                            content_type="comment",
                            external_id=cid,
                            text=top_snip.get("textDisplay", ""),
                            author=top_snip.get("authorDisplayName"),
                            timestamp=ts,
                            parent_id=video_id,
                            access_method=self.access_method,
                            compliance_status=self.compliance_status,
                            metadata={
                                "like_count": top_snip.get("likeCount", 0),
                                # main-lineage: capture the commenter's channel id so
                                # the same audience member can be tracked across
                                # comments on different videos.
                                "author_channel_id": _extract_channel_id(top_snip),
                            },
                        )
                    )
                    remaining -= 1

                    inline_replies = thread.get("replies", {}).get("comments", [])
                    total_reply_count = thread["snippet"].get("totalReplyCount", 0)
                    if total_reply_count > len(inline_replies):
                        # main-lineage: commentThreads only ships up to ~5 inline
                        # replies. Fetch the rest with comments().list — otherwise
                        # long threads silently drop most of the audience discussion.
                        inline_replies = self._fetch_all_replies(cid)

                    for reply in inline_replies:
                        r_snip = reply["snippet"]
                        r_pub = r_snip.get("publishedAt")
                        r_ts = (
                            datetime.fromisoformat(r_pub.replace("Z", "+00:00"))
                            if r_pub
                            else None
                        )
                        results.append(
                            NormalizedContent(
                                source_platform="youtube",
                                content_type="reply",
                                external_id=reply["id"],
                                text=r_snip.get("textDisplay", ""),
                                author=r_snip.get("authorDisplayName"),
                                timestamp=r_ts,
                                parent_id=cid,
                                access_method=self.access_method,
                                compliance_status=self.compliance_status,
                                metadata={
                                    "like_count": r_snip.get("likeCount", 0),
                                    "author_channel_id": _extract_channel_id(r_snip),
                                },
                            )
                        )

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

            return results

        return await asyncio.to_thread(_fetch)

    def _fetch_all_replies(self, comment_id: str) -> list[dict[str, Any]]:
        """Page through every reply for a top-level comment (main-lineage bugfix)."""
        results: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            kwargs = {"part": "snippet", "parentId": comment_id, "maxResults": 100}
            if page_token:
                kwargs["pageToken"] = page_token
            try:
                resp = self._execute(
                    self._service.comments().list(**kwargs), quota_cost=1
                )
            except HttpError as e:
                if e.resp.status == 403:
                    reason = _http_error_reason(e)
                    if reason in _QUOTA_REASONS:
                        raise QuotaExceededError(
                            f"YouTube quota/rate limit fetching replies ({reason})"
                        ) from e
                logger.warning("reply fetch for %s failed: %s", comment_id, e)
                return results
            results.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return results

    async def get_captions(self, video_id: str) -> NormalizedContent | None:
        """Fetch transcript/captions for a video (no quota cost)."""

        def _fetch() -> NormalizedContent | None:
            return fetch_youtube_caption(video_id, self.access_method, self.compliance_status)

        return await asyncio.to_thread(_fetch)

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        """Full collection: channel handle → videos + comments + captions."""
        channel_id = await self.resolve_channel(identifier)
        videos = await self.list_videos(channel_id)
        results: list[NormalizedContent] = list(videos)

        for video in videos:
            comments = await self.get_comment_threads(video.external_id)
            results.extend(comments)

            caption = await self.get_captions(video.external_id)
            if caption:
                results.append(caption)

        return results
