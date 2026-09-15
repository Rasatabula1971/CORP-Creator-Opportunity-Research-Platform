"""yt-dlp metadata adapter — YouTube channel enumeration and TikTok post metadata.

No API key and no quota. Only metadata is extracted (``skip_download``); no
media is fetched. Public metadata read this way is tagged ``open`` /
``verify`` because it bypasses the platforms' official APIs.

Comments are off by default. When enabled for YouTube, yt-dlp reads them
through YouTube's internal web endpoints, so they are tagged
``vendor_scrape`` / ``tos_risk`` and count as lower-trust evidence.

Identifier forms:
* youtube: ``@handle``, ``UC...`` channel id, or a full channel/videos URL
* tiktok:  ``@handle`` or a full profile URL
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import NormalizedContent, SourceAdapter
from corp.workers.adapters.captions import fetch_youtube_caption

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = ("youtube", "tiktok")


class _Extractor(Protocol):
    """The slice of ``yt_dlp.YoutubeDL`` this adapter uses."""

    def extract_info(self, url: str, download: bool = False) -> dict[str, Any] | None: ...


ExtractorFactory = Callable[[dict[str, Any]], _Extractor]


def _default_factory(opts: dict[str, Any]) -> _Extractor:
    import yt_dlp

    return yt_dlp.YoutubeDL(opts)


class YtDlpAdapter(SourceAdapter):
    def __init__(
        self,
        platform: str = "youtube",
        max_items: int = 50,
        include_comments: bool = False,
        max_comments: int = 100,
        extractor_factory: ExtractorFactory | None = None,
    ) -> None:
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError(f"yt-dlp adapter supports {SUPPORTED_PLATFORMS}, got {platform!r}")
        self._platform = platform
        self._max_items = max_items
        self._include_comments = include_comments
        self._max_comments = max_comments
        self._factory = extractor_factory or _default_factory

    # ── SourceAdapter contract ───────────────────────────────────────

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.VERIFY

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        return await asyncio.to_thread(self._collect_sync, identifier)

    # ── Sync implementation (yt-dlp is blocking) ─────────────────────

    @staticmethod
    def is_search(identifier: str) -> bool:
        """yt-dlp's native search syntax: ``ytsearch5:query``, ``ytsearchdate3:query``.
        A search listing spans many channels, so it has no creator profile."""
        return identifier.strip().lower().startswith("ytsearch")

    def _collect_sync(self, identifier: str) -> list[NormalizedContent]:
        url = self.profile_url(identifier)
        listing = self._factory(self._opts(flat=True)).extract_info(url, download=False) or {}

        results: list[NormalizedContent] = []
        # A search result is a synthetic playlist titled with the query; there is
        # no channel behind it, so never emit a "profile" item for one.
        profile = None if self.is_search(identifier) else self._profile_item(listing, identifier)
        if profile is not None:
            results.append(profile)

        entries = [e for e in (listing.get("entries") or []) if e][: self._max_items]
        full = self._factory(self._opts(flat=False))
        for entry in entries:
            entry_url = entry.get("url") or entry.get("webpage_url")
            if not entry_url:
                continue
            try:
                info = full.extract_info(entry_url, download=False) or {}
            except Exception as exc:  # yt-dlp raises DownloadError subclasses
                logger.warning("yt-dlp failed on %s: %s", entry_url, exc)
                continue
            video = self._video_item(info)
            results.append(video)

            if self._platform == "youtube":
                caption = fetch_youtube_caption(
                    video.external_id, self.access_method, self.compliance_status
                )
                if caption is not None:
                    results.append(caption)

            if self._include_comments:
                results.extend(self._comment_items(info, video.external_id))

        return results

    def _opts(self, *, flat: bool) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "ignoreerrors": True,
            "playlistend": self._max_items,
        }
        if flat:
            opts["extract_flat"] = "in_playlist"
        elif self._include_comments:
            opts["getcomments"] = True
            opts["extractor_args"] = {"youtube": {"max_comments": [str(self._max_comments)]}}
        return opts

    def profile_url(self, identifier: str) -> str:
        ident = identifier.strip()
        if ident.startswith(("http://", "https://")) or self.is_search(ident):
            # yt-dlp takes ``ytsearchN:query`` in the URL position as-is.
            return ident
        if self._platform == "youtube":
            if ident.startswith("UC"):
                return f"https://www.youtube.com/channel/{ident}/videos"
            handle = ident if ident.startswith("@") else f"@{ident}"
            return f"https://www.youtube.com/{handle}/videos"
        handle = ident if ident.startswith("@") else f"@{ident}"
        return f"https://www.tiktok.com/{handle}"

    # ── Mapping ──────────────────────────────────────────────────────

    def _profile_item(self, listing: dict[str, Any], identifier: str) -> NormalizedContent | None:
        followers = listing.get("channel_follower_count") or listing.get("follower_count")
        handle = listing.get("uploader_id") or listing.get("channel_id") or identifier
        name = listing.get("channel") or listing.get("uploader") or listing.get("title")
        if followers is None and name is None:
            return None
        return NormalizedContent(
            source_platform=self._platform,
            content_type="profile",
            external_id=f"profile_{handle}",
            text=listing.get("description") or name or "",
            author=name,
            url=listing.get("channel_url") or listing.get("webpage_url"),
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "handle": handle,
                "display_name": name,
                "follower_count": followers,
                "video_count": listing.get("playlist_count"),
            },
        )

    def _video_item(self, info: dict[str, Any]) -> NormalizedContent:
        description = info.get("description") or ""
        title = info.get("title") or ""
        text = f"{title}\n\n{description}".strip() if description else title
        content_type = "short" if self._platform == "tiktok" else "video"
        if self._platform == "youtube" and "/shorts/" in (info.get("webpage_url") or ""):
            content_type = "short"
        return NormalizedContent(
            source_platform=self._platform,
            content_type=content_type,
            external_id=str(info.get("id")),
            text=text,
            author=info.get("uploader") or info.get("channel"),
            timestamp=_ts(info.get("timestamp"), info.get("upload_date")),
            url=info.get("webpage_url"),
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "title": title,
                "description": description,
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "comment_count": info.get("comment_count"),
                "share_count": info.get("repost_count"),
                "duration": info.get("duration"),
                "tags": info.get("tags") or [],
                "music": (
                    (info.get("track") or info.get("album"))
                    if self._platform == "tiktok"
                    else None
                ),
                # Canonical channel identity for building a stable profile URL
                # later. ``uploader``/``channel`` (used for ``author`` above) is
                # a display name — it can contain spaces/unicode and doesn't
                # round-trip through ``profile_url``. ``channel_id`` (UC...) and
                # ``uploader_id`` (``@handle``) are yt-dlp's stable identifiers.
                "channel_id": info.get("channel_id"),
                "channel_handle": info.get("uploader_id"),
                "channel_url": info.get("channel_url") or info.get("uploader_url"),
            },
        )

    def _comment_items(self, info: dict[str, Any], video_id: str) -> list[NormalizedContent]:
        out: list[NormalizedContent] = []
        for c in (info.get("comments") or [])[: self._max_comments]:
            parent = c.get("parent") or "root"
            is_top = parent == "root"
            out.append(
                NormalizedContent(
                    source_platform=self._platform,
                    content_type="comment" if is_top else "reply",
                    external_id=str(c.get("id")),
                    text=c.get("text") or "",
                    author=c.get("author"),
                    timestamp=_ts(c.get("timestamp"), None),
                    parent_id=video_id if is_top else str(parent),
                    access_method=AccessMethod.VENDOR_SCRAPE,
                    compliance_status=ComplianceStatus.TOS_RISK,
                    metadata={"like_count": c.get("like_count", 0)},
                )
            )
        return out


def _ts(timestamp: float | None, upload_date: str | None) -> datetime | None:
    if timestamp:
        return datetime.fromtimestamp(float(timestamp), tz=UTC)
    if upload_date and len(upload_date) == 8:
        return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=UTC)
    return None
