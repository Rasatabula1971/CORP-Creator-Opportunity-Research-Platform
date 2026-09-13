"""TikTok adapter using yt-dlp — no API key required.

IMPORTANT PRECAUTIONS (read before running):
- Space out scraping sessions by 2-5 seconds between videos.
- If you scrape more than ~500 comments at a time, TikTok may trigger
  slide-CAPTCHAs — keep max_videos low (10-20) for initial runs.
- Rotate IP or use a VPN for large-scale collection to avoid 24h rate limits.
- Run from your home connection, not datacenter IPs.
- yt-dlp must be installed: pip install yt-dlp
"""

import asyncio
import json
import logging
import random
import subprocess
import time
from datetime import datetime, timezone

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import NormalizedContent, SourceAdapter

logger = logging.getLogger(__name__)

_MIN_VIDEO_DELAY = 2.0
_MAX_VIDEO_DELAY = 5.0


class TikTokAdapter(SourceAdapter):
    """Collects videos and comments from a TikTok creator via yt-dlp.

    Rate-limit precautions:
    - Randomized 2-5s delay between video fetches
    - 5-minute timeout per yt-dlp call to handle hangs
    - Graceful degradation: returns partial results on failure
    - Cookies file support for authenticated sessions
    """

    def __init__(
        self,
        max_videos: int = 20,
        include_comments: bool = True,
        cookies_file: str | None = None,
        sleep_between_videos: bool = True,
    ) -> None:
        self._max_videos = max_videos
        self._include_comments = include_comments
        self._cookies_file = cookies_file
        self._sleep_between = sleep_between_videos

    @property
    def platform(self) -> str:
        return "tiktok"

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.TOS_RISK

    def _sleep_between_videos(self) -> None:
        if self._sleep_between:
            delay = random.uniform(_MIN_VIDEO_DELAY, _MAX_VIDEO_DELAY)
            time.sleep(delay)

    def _run_ytdlp(self, url: str, extra_args: list[str] | None = None) -> list[dict]:
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-download",
            "--playlist-end", str(self._max_videos),
            "--no-warnings",
            "--quiet",
            "--sleep-interval", "2",
            "--max-sleep-interval", "5",
        ]
        if self._include_comments:
            cmd.append("--write-comments")
        if self._cookies_file:
            cmd.extend(["--cookies", self._cookies_file])
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(url)

        logger.info("Running yt-dlp for %s (max %d videos)", url, self._max_videos)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300
            )
        except subprocess.TimeoutExpired:
            logger.error("yt-dlp timed out after 5 minutes for %s", url)
            return []

        if result.returncode != 0 and not result.stdout.strip():
            stderr = result.stderr[:500] if result.stderr else ""
            if "captcha" in stderr.lower() or "verify" in stderr.lower():
                logger.error(
                    "TikTok CAPTCHA triggered — reduce max_videos or wait before retrying"
                )
            elif "429" in stderr or "rate" in stderr.lower():
                logger.error(
                    "TikTok rate-limited — wait 1-24h before retrying, or use a VPN"
                )
            else:
                logger.error("yt-dlp failed: %s", stderr)
            return []

        entries = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def _parse_video(self, entry: dict) -> NormalizedContent:
        title = entry.get("title") or entry.get("fulltitle") or ""
        description = entry.get("description") or ""
        text = f"{title}\n\n{description}".strip() if description else title

        ts = None
        timestamp_epoch = entry.get("timestamp")
        upload_date = entry.get("upload_date")
        if timestamp_epoch:
            ts = datetime.fromtimestamp(timestamp_epoch, tz=timezone.utc)
        elif upload_date and len(upload_date) == 8:
            ts = datetime(
                int(upload_date[:4]),
                int(upload_date[4:6]),
                int(upload_date[6:8]),
                tzinfo=timezone.utc,
            )

        video_id = entry.get("id", "")
        uploader = entry.get("uploader") or entry.get("channel")

        return NormalizedContent(
            source_platform="tiktok",
            content_type="video",
            external_id=video_id,
            text=text,
            author=uploader,
            timestamp=ts,
            url=entry.get("webpage_url") or f"https://www.tiktok.com/@{uploader}/video/{video_id}",
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "view_count": entry.get("view_count", 0),
                "like_count": entry.get("like_count", 0),
                "comment_count": entry.get("comment_count", 0),
                "share_count": entry.get("repost_count", 0),
                "duration": entry.get("duration"),
                "hashtags": entry.get("tags", []),
                "track": entry.get("track"),
                "artist": entry.get("artist"),
            },
        )

    def _parse_comments(self, entry: dict) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        comments = entry.get("comments") or []
        video_id = entry.get("id", "")

        for c in comments:
            text = c.get("text", "")
            if not text:
                continue

            ts = None
            c_ts = c.get("timestamp")
            if c_ts:
                ts = datetime.fromtimestamp(c_ts, tz=timezone.utc)

            comment_id = str(c.get("id", ""))
            parent = c.get("parent")
            is_reply = parent and parent != "root"

            results.append(
                NormalizedContent(
                    source_platform="tiktok",
                    content_type="reply" if is_reply else "comment",
                    external_id=comment_id,
                    text=text,
                    author=c.get("author"),
                    timestamp=ts,
                    parent_id=str(parent) if is_reply else video_id,
                    access_method=self.access_method,
                    compliance_status=self.compliance_status,
                    metadata={
                        "like_count": c.get("like_count", 0),
                        "video_id": video_id,
                    },
                )
            )

        return results

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        """Collect videos and comments from a TikTok creator.

        Args:
            identifier: TikTok username (e.g. "username" or "@username").
        """
        handle = identifier.strip().lstrip("@")
        url = f"https://www.tiktok.com/@{handle}"
        logger.info("Collecting TikTok data for @%s", handle)

        entries = await asyncio.to_thread(self._run_ytdlp, url)
        logger.info("yt-dlp returned %d entries for @%s", len(entries), handle)

        results: list[NormalizedContent] = []
        for entry in entries:
            results.append(self._parse_video(entry))
            if self._include_comments:
                results.extend(self._parse_comments(entry))

        logger.info(
            "TikTok collection complete: %d total items for @%s",
            len(results),
            handle,
        )
        return results
