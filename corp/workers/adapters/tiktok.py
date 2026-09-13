"""TikTok adapter using yt-dlp — no API key required."""

import asyncio
import json
import logging
import subprocess
from datetime import datetime, timezone

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import NormalizedContent, SourceAdapter

logger = logging.getLogger(__name__)


class TikTokAdapter(SourceAdapter):
    """Collects videos and comments from a TikTok creator via yt-dlp."""

    def __init__(
        self,
        max_videos: int = 50,
        include_comments: bool = True,
    ) -> None:
        self._max_videos = max_videos
        self._include_comments = include_comments

    @property
    def platform(self) -> str:
        return "tiktok"

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.TOS_RISK

    def _run_ytdlp(self, url: str, extra_args: list[str] | None = None) -> list[dict]:
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-download",
            "--playlist-end", str(self._max_videos),
            "--no-warnings",
            "--quiet",
        ]
        if self._include_comments:
            cmd.append("--write-comments")
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(url)

        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )

        if result.returncode != 0 and not result.stdout.strip():
            logger.error("yt-dlp failed: %s", result.stderr[:500])
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
        upload_date = entry.get("upload_date")
        timestamp_epoch = entry.get("timestamp")
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
