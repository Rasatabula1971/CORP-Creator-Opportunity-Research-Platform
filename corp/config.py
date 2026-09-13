from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://corp:corp@localhost:5432/corp"
    database_url_sync: str = "postgresql://corp:corp@localhost:5432/corp"

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

    # LLM provider selection: auto | fair | gemini (auto prefers FAIR when FAIR_URL is set)
    llm_provider: str = "auto"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    fair_url: str = ""
    fair_client_id: str = "corp"
    fair_api_key: str = ""
    fair_quality_level: str = "standard"
    fair_priority: str = "P2"
    fair_timeout_seconds: float = 60.0

    scoring_rules_path: str = "rules/scoring.yaml"
    intent_rules_path: str = "rules/intent.yaml"

    # A run whose per-item failure rate exceeds this is marked "partial", not "completed".
    pipeline_max_failure_rate: float = 0.2
    embedding_model: str = "all-MiniLM-L6-v2"

    app_env: str = "development"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000)
    # When set, every endpoint except /health requires header X-Api-Key to match.
    api_key: str = ""
    # Comma-separated origins for CORS; "*" allows all (fine for local dev only).
    cors_origins: str = "*"


settings = Settings()
