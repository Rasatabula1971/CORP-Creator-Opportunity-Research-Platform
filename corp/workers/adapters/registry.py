"""Adapter selection — builds a SourceAdapter for a platform name from settings."""

import logging

from corp.config import Settings
from corp.config import settings as default_settings
from corp.workers.adapters.base import SourceAdapter

logger = logging.getLogger(__name__)

KNOWN_PLATFORMS = (
    "youtube", "reddit", "tiktok", "web", "stackexchange",
    "searchdemand", "amazon_reviews", "marketplace",
    "hackernews", "wikipedia", "googletrends", "appstore", "crowdfunding",
    "patreon_substack",
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


def _usable_marketplaces(cfg: Settings) -> list[str]:
    """MARKETPLACE_SITES minus the sites that cannot answer (ADR-0066).

    Udemy's Affiliate API, the only public endpoint the adapter ever used,
    was discontinued on 2025-01-01: every request is a 403. Etsy's search
    page is behind DataDome, which refuses non-browser clients outright, so
    without an Open API key the scrape is a guaranteed 403 per keyword. Both
    are dropped here, with a warning, rather than spent on and then
    circuit-broken as if they were merely down.
    """
    sites = [s.strip().lower() for s in cfg.marketplace_sites.split(",") if s.strip()]
    usable: list[str] = []
    for site in sites:
        if site == "udemy":
            _warn_once(
                "udemy",
                "Marketplace site 'udemy' ignored: Udemy's Affiliate API was "
                "discontinued on 2025-01-01 and the endpoint returns 403",
            )
            continue
        if site == "etsy" and not cfg.etsy_api_key:
            _warn_once(
                "etsy",
                "Marketplace site 'etsy' ignored: the search page is bot-blocked "
                "(DataDome); set ETSY_API_KEY to use the official Open API instead",
            )
            continue
        usable.append(site)
    return usable


# The marketplace adapter is rebuilt for every keyword of every drill, so a
# configuration notice that repeated on each build drowned the API log.
# Once per site per process is enough; later builds log it at debug.
_warned_marketplace_sites: set[str] = set()


def _warn_once(site: str, message: str) -> None:
    if site in _warned_marketplace_sites:
        logger.debug(message)
        return
    _warned_marketplace_sites.add(site)
    logger.warning(message)


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

        sites = _usable_marketplaces(cfg)
        if not sites:
            raise AdapterConfigError(
                "no usable marketplace: MARKETPLACE_SITES is empty once blocked "
                "sites are removed (Udemy is discontinued; Etsy needs ETSY_API_KEY)"
            )
        return MarketplaceAdapter(
            max_listings=cfg.marketplace_max_listings,
            marketplaces=sites,
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

    if name == "crowdfunding":
        from corp.workers.adapters.crowdfunding import CrowdfundingAdapter

        return CrowdfundingAdapter(max_projects=cfg.crowdfunding_max_projects)

    if name == "patreon_substack":
        from corp.workers.adapters.patreon_substack import PatreonSubstackAdapter

        return PatreonSubstackAdapter(max_creators=cfg.patreon_substack_max_creators)

    known = ", ".join(KNOWN_PLATFORMS)
    raise AdapterConfigError(f"Unknown platform {platform!r}; known: {known}")
