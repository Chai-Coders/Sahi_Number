from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    serpapi_api_key: str = ""
    serpapi_mode: str = "replay"
    hourly_search_limit: int = 45
    min_credits_reserve: int = 20
    max_searches_per_check: int = 8
    cache_ttl_seconds: int = 3600
    enable_ads: bool = True
    enable_ai_overview: bool = True
    enable_reviews: bool = True
    device: str = "mobile"
    database_path: Path = ROOT / "data" / "sahi.db"
    fixture_path: Path = ROOT / "tests" / "fixtures"

    @property
    def effective_mode(self) -> str:
        return "live" if self.serpapi_mode == "live" and self.serpapi_api_key else "replay"


@lru_cache
def get_settings() -> Settings:
    return Settings()
