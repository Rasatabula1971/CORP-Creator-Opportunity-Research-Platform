"""YouTube Data API v3 adapter."""

import asyncio
import logging
import re
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


def _parse_duration(iso_duration: str) -> int:
    """Parse ISO 8601 duration (e.g. 'PT4M13S') to total seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration or "")
    if not match:
        return 0
    h, m, s = (int(g or 0) for g in match.groups())
    return h * 3600 + m * 60 + s


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

            video_details: dict[str, dict] = {}
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i : i + 50]
                resp = self._execute(
                    self._service.videos().list(
                        part="statistics,contentDetails,snippet",
                        id=",".join(batch),
                    ),
                    quota_cost=1,
                )
                for item in resp.get("items", []):
                    video_details[item["id"]] = item

            results: list[NormalizedContent] = []
            for vid_id in video_ids:
                snip = snippets[vid_id]
                detail = video_details.get(vid_id, {})
                st = detail.get("statistics", {})
                cd = detail.get("contentDetails", {})
                vid_snip = detail.get("snippet", {})

                duration = _parse_duration(cd.get("duration", ""))
                tags = vid_snip.get("tags", [])
                language = (
                    vid_snip.get("defaultAudioLanguage")
                    or vid_snip.get("defaultLanguage")
                )

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
                            "duration": duration,
                            "tags": tags,
                            "language": language,
                            "is_short": 0 < duration <= 60,
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
                        reason = ""
                        if hasattr(e, "error_details") and e.error_details:
                            reason = str(e.error_details)
                        elif hasattr(e, "reason"):
                            reason = e.reason or ""
                        if "commentsDisabled" in reason or "forbidden" in reason.lower():
                            logger.warning("Comments disabled for video %s", video_id)
                            return results
                        logger.error(
                            "HTTP 403 fetching comments for %s (not disabled): %s",
                            video_id, reason,
                        )
                        raise
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
                                "author_channel_id": top_snip.get(
                                    "authorChannelId", {}
                                ).get("value"),
                            },
                        )
                    )
                    remaining -= 1

                    total_reply_count = thread["snippet"].get("totalReplyCount", 0)
                    inline_replies = thread.get("replies", {}).get("comments", [])

                    if total_reply_count > len(inline_replies):
                        all_replies = self._fetch_all_replies(cid)
                    else:
                        all_replies = inline_replies

                    for reply in all_replies:
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
                                    "author_channel_id": r_snip.get(
                                        "authorChannelId", {}
                                    ).get("value"),
                                },
                            )
                        )

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

            return results

        return await asyncio.to_thread(_fetch)

    def _fetch_all_replies(self, parent_comment_id: str) -> list[dict]:
        """Paginate through all replies for a comment thread."""
        replies: list[dict] = []
        page_token: str | None = None
        while True:
            kwargs: dict = {
                "part": "snippet",
                "parentId": parent_comment_id,
                "maxResults": 100,
                "textFormat": "plainText",
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = self._execute(
                self._service.comments().list(**kwargs), quota_cost=1
            )
            replies.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return replies

    async def get_captions(self, video_id: str) -> NormalizedContent | None:
        """Fetch transcript/captions for a video (no quota cost)."""

        def _fetch() -> NormalizedContent | None:
            from youtube_transcript_api import YouTubeTranscriptApi
            from youtube_transcript_api._errors import (
                TranscriptsDisabled,
                NoTranscriptFound,
                VideoUnavailable,
            )

            try:
                api = YouTubeTranscriptApi()
                transcript = api.fetch(video_id)
                segments = [
                    {"text": s.text, "start": s.start, "duration": s.duration}
                    for s in transcript
                ]
                text = " ".join(s["text"] for s in segments)
                return NormalizedContent(
                    source_platform="youtube",
                    content_type="caption",
                    external_id=f"caption_{video_id}",
                    text=text,
                    parent_id=video_id,
                    access_method=self.access_method,
                    compliance_status=self.compliance_status,
                    metadata={"segments": segments},
                )
            except (TranscriptsDisabled, NoTranscriptFound):
                logger.debug("No captions available for video %s", video_id)
                return None
            except VideoUnavailable:
                logger.warning("Video unavailable for captions: %s", video_id)
                return None
            except Exception:
                logger.exception("Unexpected error fetching captions for %s", video_id)
                return None

        return await asyncio.to_thread(_fetch)

    async def get_channel_info(self, channel_id: str) -> dict:
        """Fetch channel-level statistics, snippet, and branding."""

        def _fetch() -> dict:
            req = self._service.channels().list(
                part="statistics,snippet,brandingSettings", id=channel_id
            )
            resp = self._execute(req, quota_cost=1)
            if not resp.get("items"):
                return {}
            item = resp["items"][0]
            st = item.get("statistics", {})
            snip = item.get("snippet", {})
            joined = snip.get("publishedAt")
            return {
                "subscriber_count": int(st.get("subscriberCount", 0)),
                "total_view_count": int(st.get("viewCount", 0)),
                "video_count": int(st.get("videoCount", 0)),
                "country": snip.get("country"),
                "description": snip.get("description"),
                "joined_at": joined,
            }

        return await asyncio.to_thread(_fetch)

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        """Full collection: channel handle → videos + comments + captions."""
        channel_id = await self.resolve_channel(identifier)

        channel_info = await self.get_channel_info(channel_id)
        results: list[NormalizedContent] = []
        if channel_info:
            results.append(
                NormalizedContent(
                    source_platform="youtube",
                    content_type="channel_metadata",
                    external_id=channel_id,
                    text="",
                    access_method=self.access_method,
                    compliance_status=self.compliance_status,
                    metadata=channel_info,
                )
            )

        videos = await self.list_videos(channel_id)
        results.extend(videos)

        async def _collect_video_extras(video: NormalizedContent) -> list[NormalizedContent]:
            extras: list[NormalizedContent] = []
            comments = await self.get_comment_threads(video.external_id)
            extras.extend(comments)
            caption = await self.get_captions(video.external_id)
            if caption:
                extras.append(caption)
            return extras

        sem = asyncio.Semaphore(5)

        async def _limited(video: NormalizedContent) -> list[NormalizedContent]:
            async with sem:
                return await _collect_video_extras(video)

        batches = await asyncio.gather(*[_limited(v) for v in videos])
        for batch in batches:
            results.extend(batch)

        return results
