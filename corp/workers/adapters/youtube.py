"""YouTube Data API v3 adapter."""

import asyncio
import logging
import threading
import time
from datetime import datetime

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

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    """Raised when YouTube API daily quota would be exceeded."""


def _is_retryable_http_error(exc: BaseException) -> bool:
    if not isinstance(exc, HttpError):
        return False
    return exc.resp.status in (429, 500, 502, 503, 504)


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
    def _execute(self, request: object, quota_cost: int = 1) -> dict:
        self._check_quota(quota_cost)
        self._limiter.acquire()
        result = request.execute()  # type: ignore[union-attr]
        self._quota_used += quota_cost
        return result

    # ---- public API (all async, sync work dispatched to thread) ----

    async def resolve_channel(self, handle: str) -> str:
        """Resolve a channel handle (e.g. '@mkbhd') to a channel ID."""
        clean = handle.lstrip("@")

        def _resolve() -> str:
            req = self._service.channels().list(part="id", forHandle=clean)
            resp = self._execute(req, quota_cost=1)
            if resp.get("items"):
                return resp["items"][0]["id"]

            req = self._service.channels().list(part="id", forUsername=clean)
            resp = self._execute(req, quota_cost=1)
            if resp.get("items"):
                return resp["items"][0]["id"]

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
            snippets: dict[str, dict] = {}
            page_token: str | None = None
            remaining = limit

            while remaining > 0:
                kwargs: dict = {
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

            stats: dict[str, dict] = {}
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i : i + 50]
                resp = self._execute(
                    self._service.videos().list(
                        part="statistics", id=",".join(batch)
                    ),
                    quota_cost=1,
                )
                for item in resp.get("items", []):
                    stats[item["id"]] = item.get("statistics", {})

            results: list[NormalizedContent] = []
            for vid_id in video_ids:
                snip = snippets[vid_id]
                st = stats.get(vid_id, {})
                pub = snip.get("publishedAt")
                ts = datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None

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
                kwargs: dict = {
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
                        logger.warning("Comments disabled for video %s", video_id)
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
                            metadata={"like_count": top_snip.get("likeCount", 0)},
                        )
                    )
                    remaining -= 1

                    for reply in thread.get("replies", {}).get("comments", []):
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
                                metadata={"like_count": r_snip.get("likeCount", 0)},
                            )
                        )

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

            return results

        return await asyncio.to_thread(_fetch)

    async def get_captions(self, video_id: str) -> NormalizedContent | None:
        """Fetch transcript/captions for a video (no quota cost)."""

        def _fetch() -> NormalizedContent | None:
            try:
                from youtube_transcript_api import YouTubeTranscriptApi

                api = YouTubeTranscriptApi()
                transcript = api.fetch(video_id)
                text = " ".join(snippet.text for snippet in transcript)
                return NormalizedContent(
                    source_platform="youtube",
                    content_type="caption",
                    external_id=f"caption_{video_id}",
                    text=text,
                    parent_id=video_id,
                    access_method=self.access_method,
                    compliance_status=self.compliance_status,
                )
            except Exception:
                logger.debug("No captions for video %s", video_id)
                return None

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
