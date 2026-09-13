"""Adapter selection — builds a SourceAdapter for a platform name from settings."""

from corp.config import Settings
from corp.config import settings as default_settings
from corp.workers.adapters.base import SourceAdapter


class AdapterConfigError(Exception):
    """The requested platform is unknown or not configured."""


def build_adapter(platform: str, cfg: Settings | None = None) -> SourceAdapter:
    cfg = cfg or default_settings
    name = platform.lower()

    if name == "youtube":
        if not cfg.youtube_api_key:
            raise AdapterConfigError("youtube adapter requires YOUTUBE_API_KEY")
        from corp.workers.adapters.youtube import YouTubeAdapter

        return YouTubeAdapter(
            api_key=cfg.youtube_api_key,
            daily_quota=cfg.youtube_daily_quota_units,
            requests_per_second=cfg.youtube_requests_per_second,
        )

    if name == "reddit":
        from corp.workers.adapters.reddit import RedditAdapter

        return RedditAdapter(
            user_agent=cfg.reddit_user_agent,
            posts_per_creator=cfg.reddit_posts_per_creator,
            request_interval_seconds=cfg.reddit_request_interval_seconds,
        )

    raise AdapterConfigError(f"Unknown platform {platform!r}; known: youtube, reddit")
