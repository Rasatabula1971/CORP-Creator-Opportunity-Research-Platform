from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = ""
    database_url_sync: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30

    youtube_api_key: str = ""
    youtube_daily_quota_units: int = 10000
    youtube_requests_per_second: int = 5

    # Reddit public JSON feeds (no credentials). Reddit asks for a descriptive UA
    # and limits unauthenticated clients to roughly 10 requests per minute.
    reddit_user_agent: str = "corp-research/0.1 (creator opportunity research)"
    reddit_posts_per_creator: int = 25
    reddit_request_interval_seconds: float = 6.0

    # yt-dlp metadata adapter (YouTube channel enumeration when no API key; TikTok).
    ytdlp_max_items: int = 50
    ytdlp_include_comments: bool = False  # YouTube comments via yt-dlp are tagged tos_risk

    # Creator-web adapter (landing page + commerce-looking outbound pages).
    web_max_pages: int = 8

    # Stack Exchange adapter (niche-signal: questions = audience problems).
    # Open API, no key required. Optional key raises quota from 300 to 10,000/day.
    stackexchange_api_key: str = ""
    stackexchange_site: str = "stackoverflow"
    stackexchange_max_questions: int = 50
    stackexchange_include_answers: bool = True

    # Search-demand adapter (niche-signal: Google autocomplete suggestions).
    searchdemand_max_suggestions: int = 50
    searchdemand_language: str = "en"
    searchdemand_country: str = "us"

    # Amazon review adapter (niche-signal: 1-3 star reviews as unmet-need signals).
    amazon_max_reviews: int = 50
    amazon_max_products: int = 5

    # Marketplace adapter (niche-signal: Gumroad/Etsy listings for saturation + pricing).
    # Udemy is no longer a valid site: its Affiliate API (the only public
    # endpoint) was discontinued on 2025-01-01 and returns 403 for good; the
    # registry drops it with a warning if it is listed (ADR-0066).
    marketplace_max_listings: int = 30
    marketplace_sites: str = "gumroad"
    # Etsy Open API v3 key (Personal App tier). REQUIRED for Etsy: the HTML
    # search page sits behind DataDome, which answers every non-browser
    # client with 403, so without a key the registry leaves Etsy out rather
    # than burn a blocked request per keyword (ADR-0066). Register at
    # https://www.etsy.com/developers.
    etsy_api_key: str = ""

    # Hacker News adapter (niche-signal: stories + comments via Algolia API). Fully open.
    hackernews_max_items: int = 50

    # Wikipedia adapter (niche-signal: pageview trends as demand validation). Official API.
    wikipedia_max_articles: int = 10
    wikipedia_pageview_days: int = 30

    # Google Trends adapter (niche-signal: trending topics RSS + optional pytrends).
    googletrends_max_items: int = 50
    googletrends_geo: str = "US"

    # Apple App Store adapter (niche-signal: review RSS + iTunes Search). Open, no key.
    appstore_max_reviews: int = 50
    appstore_max_apps: int = 5
    appstore_country: str = "us"

    # Crowdfunding adapter (niche-signal: Kickstarter + Indiegogo backing as
    # purchase-intent evidence). Both platforms' internal search endpoints;
    # no official API, no key. Off by default via discovery_disabled_sources
    # below: since 2026-09 both sit behind edge bot protection that refuses
    # any non-browser client, browser headers included (ADR-0066).
    crowdfunding_max_projects: int = 30

    # Grey-source egress (ADR-0067). The adapters that scrape pages without an
    # official API (Amazon reviews, marketplace HTML, crowdfunding) are the
    # ones a site may block, and a block lands on whatever address sent the
    # request. Point GREY_PROXY_URL at a proxy (http://user:pass@host:port or
    # socks5://...; socks needs the httpx[socks] extra) so a ban burns the
    # proxy's address, not the operator's home connection. Official-API and
    # honest-UA adapters (YouTube, Reddit, Stack Exchange, HN, Wikipedia, web)
    # stay direct. With GREY_PROXY_REQUIRED=true the grey adapters refuse to
    # build without a proxy instead of silently falling back to the home IP.
    grey_proxy_url: str = ""
    grey_proxy_required: bool = False
    grey_proxy_platforms: str = "amazon_reviews,marketplace,crowdfunding"

    # Patreon + Substack adapter (niche-signal: creator monetisation --
    # paid tiers, pricing, subscriber counts). Substack's internal search
    # endpoint, verified live, no key. Patreon not yet implemented (its
    # real public data was never verified -- see the adapter's docstring).
    patreon_substack_max_creators: int = 30

    # Source health tracker — circuit breaker for tolerated adapters.
    # Consecutive failures before degrading a source.
    health_degrade_after: int = 3
    # Consecutive failures before disconnecting a source (skipped in multi-source runs).
    health_disconnect_after: int = 6
    # Seconds before a disconnected source gets a probe attempt.
    health_probe_cooldown_seconds: float = 3600.0

    # Multi-source niche discovery — comma-separated platforms to include.
    # Defaults to all niche-family adapters.
    niche_discovery_platforms: str = ""
    # Niche-discovery fan-out platforms to leave out entirely (comma-separated
    # names from NICHE_FAN_OUT_PLATFORMS). A disabled source is neither built
    # nor counted against source health; the run records it as skipped with
    # this reason. Distinct from the circuit breaker, which is for sources
    # that are meant to work but currently don't.
    discovery_disabled_sources: str = "crowdfunding"

    # Bulk research artifacts (raw payloads, JSONL archives) — §24. Relational
    # rows stay in Postgres; this is the external SD/SSD side, so it must be
    # configurable to move without a code change.
    corp_data_path: str = "corp_data"

    # SQLite warm store for bulk data (evidence text, embeddings, content,
    # interactions, metrics). Lives on external/flash storage to keep
    # Supabase Postgres within the free-tier 500 MB limit.
    warm_store_path: str = "corp_data/warm.db"

    # LLM provider selection: auto | fair | gemini | groq | pool
    # auto prefers FAIR (in-process, every free provider it has a key for)
    # when the fair package is installed and FAIR_ENABLED is true; otherwise
    # it pools every configured key in LLM_PROVIDER_ORDER and fails over when
    # one hits its quota.
    llm_provider: str = "auto"
    llm_provider_order: str = "gemini,groq"
    # How long a provider sits out after a daily-cap error, in seconds.
    llm_cooldown_seconds: float = 3600.0
    # Longest the pool will wait for a short cooldown to expire when no
    # provider is available, before failing the call.
    llm_max_wait_seconds: float = 300.0

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_timeout_seconds: float = 60.0
    # Groq reserves this against its 8,000 tokens/minute bucket, so it directly
    # sets calls per minute. Measured extraction completions stay under 500.
    groq_max_output_tokens: int = 2048
    # gpt-oss is a reasoning model; "low" spends ~16 reasoning tokens per call
    # instead of ~500, which is what keeps the free tier's per-minute token
    # limit from throttling every other call. Empty string sends no preference.
    groq_reasoning_effort: str = "low"

    # FAIR Free AI Router, embedded (pip install -e <FAIR repo>). It reads
    # GEMINI_API_KEY/GROQ_API_KEY from the settings above; FAIR_ENV_FILE points
    # at FAIR's own .env for the keys of its other free providers.
    fair_enabled: bool = True
    # Free-only enforcement. When true, LLM_PROVIDER=auto will NOT fall back to
    # the raw Gemini/Groq pool if FAIR is unusable: the raw providers bypass
    # FAIR's free-only attestation, so a key on a billable account could incur
    # charges. With it true, an LLM call fails closed instead. Left false by
    # default to preserve the pool fallback; set FAIR_REQUIRED=true to guarantee
    # every call goes through FAIR's cost check.
    fair_required: bool = False
    fair_env_file: str = ""
    fair_client_id: str = "corp"
    # FAIR routes to a recurring free-tier provider (Gemini, Groq, Mistral,
    # Z.ai, Cloudflare Workers AI) only when the operator attests that the
    # account behind the key is free-only and cannot auto-bill. Comma-separated
    # FAIR provider ids: google_gemini_api, groq, mistral, zai_free,
    # cloudflare_workers_ai. A keyed provider missing from this list is left
    # out by FAIR with a "confirmation required" reason (see
    # /providers/health). OpenRouter Free and Kilo Free need no confirmation:
    # FAIR verifies a zero price on every call.
    fair_confirmed_free_providers: str = ""
    # Models that never answered (down, slow, throttled) tolerated per FAIR
    # solve before it escalates; separate from FAIR's max_attempts, which
    # counts answers its quality gate judged.
    fair_max_unanswered_attempts: int = 6
    # commodity | standard | advanced | high_impact_support. Schema-validated
    # answers (what CORP's prompts produce) pass at commodity/standard only.
    fair_quality_level: str = "standard"
    fair_priority: str = "P2"
    fair_timeout_seconds: float = 60.0
    fair_max_output_tokens: int = 2048
    fair_cache_enabled: bool = True

    scoring_rules_path: str = "rules/scoring.yaml"
    intent_rules_path: str = "rules/intent.yaml"
    niche_qualification_rules_path: str = "rules/niche_qualification.yaml"
    broad_topics_path: str = "rules/broad_topics.yaml"

    # CORP1 Step 1 Level 0 — the autonomous discovery crawler. Off by
    # default: enabling it means unattended LLM spend on every tick, so
    # that is an explicit opt-in, not something installing CORP turns on.
    # POST /discovery/run triggers a pass by hand either way.
    discovery_enabled: bool = False
    discovery_interval_seconds: int = 86_400
    # None = use topics_per_pass from rules/broad_topics.yaml.
    discovery_topics_per_pass: int | None = None
    # Where Level 0 momentum comes from. "youtube" is the official Data API
    # (needs YOUTUBE_API_KEY; ~15-30 quota units per pass). "googletrends" is
    # the RSS/pytrends path the Google Trends adapter labels "tolerated/
    # undocumented". "none" ranks purely by least-recently-researched. A
    # source whose prerequisites are missing degrades to that same rotation.
    discovery_momentum_source: Literal["youtube", "googletrends", "none"] = "youtube"

    # Creator-first discovery: a researched creator's audience problem
    # clusters become micro-niche suggestions, held for approval before
    # anything is drilled. A cluster needs this many observations to count,
    # and its creator's known follower count must sit inside the band
    # (the spec's 10K-200K partnership range).
    micro_niche_min_frequency: int = 3
    micro_niche_min_followers: int = 10_000
    micro_niche_max_followers: int = 200_000

    @field_validator("discovery_topics_per_pass", mode="before")
    @classmethod
    def _blank_means_unset(cls, v: object) -> object:
        """Treat DISCOVERY_TOPICS_PER_PASS= (blank) as unset.

        .env files carry everything as strings, and a commented-out
        "leave blank for the default" line is exactly how someone
        expresses "no override". Without this, copying .env.example and
        leaving the value empty crashes the app at import with an
        int_parsing error before anything logs.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    # A run whose per-item failure rate exceeds this is marked "partial", not "completed".
    pipeline_max_failure_rate: float = 0.2
    embedding_model: str = "all-MiniLM-L6-v2"

    app_env: str = "development"
    db_echo: bool = False
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    # 8010, matching start_corp.bat and the dashboard's default API base URL
    # (web/src/api/client.ts). Note that nothing in the app reads this: the
    # server is launched by the uvicorn CLI, so uvicorn's own --port decides
    # what it binds. start_corp.bat reads API_PORT out of .env and passes it
    # through; a manual `uvicorn ...` run must pass --port itself or it will
    # silently bind uvicorn's default 8000 and the dashboard will not find it.
    api_port: int = Field(default=8010)
    # When set, every endpoint except /health requires header X-Api-Key to match.
    api_key: str = ""
    # Comma-separated origins for CORS. Defaults to the local Vite dev server;
    # set explicitly for any non-local deployment. "*" is never used as a fallback.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


settings = Settings()
