"""Adapter selection — builds a SourceAdapter for a platform name from settings."""

from corp.config import Settings
from corp.config import settings as default_settings
from corp.workers.adapters.base import SourceAdapter

KNOWN_PLATFORMS = (
    "youtube", "reddit", "tiktok", "web", "stackexchange",
    "searchdemand", "amazon_reviews", "marketplace",
    "hackernews", "wikipedia", "googletrends", "appstore",
)


class AdapterConfigError(Exception):
    """The requested platform is unknown or not configured."""


def build_search_adapter(platform: str = "youtube", cfg: Settings | None = None) -> SourceAdapter:
    """Adapter for creator DISCOVERY via keyword search (``ytsearchN:`` syntax).

    Distinct from :func:`build_adapter`: the YouTube Data API adapter resolves a
    single known channel handle, but discovery searches *across* channels, which
    only the yt-dlp adapter supports. A YouTube API key, when present, is used to
    enrich subscriber counts (``YouTubeAPIEnricher``), never for search — so this
    always returns the search-capable yt-dlp adapter regardless of the key.
    """
    cfg = cfg or default_settings
    name = platform.lower()
    if name in ("youtube", "tiktok"):
        from corp.workers.adapters.ytdlp import YtDlpAdapter

        return YtDlpAdapter(platform=name, max_items=cfg.ytdlp_max_items)
    raise AdapterConfigError(f"Search discovery not supported for platform {platform!r}")


def build_adapter(platform: str, cfg: Settings | None = None) -> SourceAdapter:
    cfg = cfg or default_settings
    name = platform.lower()

    if name == "youtube":
        if cfg.youtube_api_key:
            from corp.workers.adapters.youtube import YouTubeAdapter

            return YouTubeAdapter(
                api_key=cfg.youtube_api_key,
                daily_quota=cfg.youtube_daily_quota_units,
                requests_per_second=cfg.youtube_requests_per_second,
            )
        # No API key: fall back to yt-dlp metadata (no comments unless opted in).
        from corp.workers.adapters.ytdlp import YtDlpAdapter

        return YtDlpAdapter(
            platform="youtube",
            max_items=cfg.ytdlp_max_items,
            include_comments=cfg.ytdlp_include_comments,
        )

    if name == "tiktok":
        from corp.workers.adapters.ytdlp import YtDlpAdapter

        return YtDlpAdapter(platform="tiktok", max_items=cfg.ytdlp_max_items)

    if name == "web":
        from corp.workers.adapters.web import WebPresenceAdapter

        return WebPresenceAdapter(max_pages=cfg.web_max_pages)

    if name == "reddit":
        from corp.workers.adapters.reddit import RedditAdapter

        return RedditAdapter(
            user_agent=cfg.reddit_user_agent,
            posts_per_creator=cfg.reddit_posts_per_creator,
            request_interval_seconds=cfg.reddit_request_interval_seconds,
        )

    if name == "stackexchange":
        from corp.workers.adapters.stackexchange import StackExchangeAdapter

        return StackExchangeAdapter(
            site=cfg.stackexchange_site,
            max_questions=cfg.stackexchange_max_questions,
            include_answers=cfg.stackexchange_include_answers,
            api_key=cfg.stackexchange_api_key or None,
        )

    if name == "searchdemand":
        from corp.workers.adapters.searchdemand import SearchDemandAdapter

        return SearchDemandAdapter(
            max_suggestions=cfg.searchdemand_max_suggestions,
            language=cfg.searchdemand_language,
            country=cfg.searchdemand_country,
        )

    if name == "amazon_reviews":
        from corp.workers.adapters.amazonreviews import AmazonReviewAdapter

        return AmazonReviewAdapter(
            max_reviews=cfg.amazon_max_reviews,
            max_products=cfg.amazon_max_products,
        )

    if name == "marketplace":
        from corp.workers.adapters.marketplace import MarketplaceAdapter

        sites = [s.strip() for s in cfg.marketplace_sites.split(",") if s.strip()]
        return MarketplaceAdapter(
            max_listings=cfg.marketplace_max_listings,
            marketplaces=sites or None,
            etsy_api_key=cfg.etsy_api_key or None,
        )

    if name == "hackernews":
        from corp.workers.adapters.hackernews import HackerNewsAdapter

        return HackerNewsAdapter(
            max_items=cfg.hackernews_max_items,
        )

    if name == "wikipedia":
        from corp.workers.adapters.wikipedia import WikipediaAdapter

        return WikipediaAdapter(
            max_articles=cfg.wikipedia_max_articles,
            pageview_days=cfg.wikipedia_pageview_days,
        )

    if name == "googletrends":
        from corp.workers.adapters.googletrends import GoogleTrendsAdapter

        return GoogleTrendsAdapter(
            max_items=cfg.googletrends_max_items,
            geo=cfg.googletrends_geo,
        )

    if name == "appstore":
        from corp.workers.adapters.appstore import AppStoreAdapter

        return AppStoreAdapter(
            max_reviews=cfg.appstore_max_reviews,
            max_apps=cfg.appstore_max_apps,
            country=cfg.appstore_country,
        )

    known = ", ".join(KNOWN_PLATFORMS)
    raise AdapterConfigError(f"Unknown platform {platform!r}; known: {known}")
