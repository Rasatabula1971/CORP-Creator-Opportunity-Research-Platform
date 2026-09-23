from pydantic import Field
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

    # Marketplace adapter (niche-signal: Gumroad/Etsy/Udemy listings for saturation + pricing).
    marketplace_max_listings: int = 30
    marketplace_sites: str = "gumroad,etsy,udemy"
    # Etsy Open API v3 key (Personal App tier). When set, Etsy uses official API
    # instead of HTML scraping. Register at https://www.etsy.com/developers.
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
    # purchase-intent evidence). Both platforms' internal search endpoints,
    # verified live; no official API, no key.
    crowdfunding_max_projects: int = 30

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
    gemini_model: str = "gemini-2.0-flash"

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
    fair_env_file: str = ""
    fair_client_id: str = "corp"
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
