from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    database_url: str
    fred_api_key: str = ""

    claude_model: str = "claude-haiku-5-5"
    analysis_concurrency: int = 4
    news_lookback_hours: int = 48
    max_items_per_feed: int = 25
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
