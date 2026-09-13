from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://corp:corp@localhost:5432/corp"
    database_url_sync: str = "postgresql://corp:corp@localhost:5432/corp"

    youtube_api_key: str = ""
    youtube_daily_quota_units: int = 10000
    youtube_requests_per_second: int = 5

    gemini_api_key: str = ""

    instagram_username: str = ""
    instagram_password: str = ""

    fair_url: str = ""
    fair_client_id: str = "corp"
    fair_api_key: str = ""

    scoring_rules_path: str = "rules/scoring.yaml"
    intent_rules_path: str = "rules/intent.yaml"

    app_env: str = "development"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000)


settings = Settings()
