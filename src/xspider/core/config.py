"""Configuration management using Pydantic Settings."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TwitterToken(BaseSettings):
    """Single Twitter authentication token."""

    bearer_token: str
    ct0: str
    auth_token: str

    model_config = SettingsConfigDict(frozen=True)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Twitter tokens
    twitter_tokens: list[TwitterToken] = Field(default_factory=list)

    # Proxy configuration
    proxy_urls: list[str] = Field(default_factory=list)

    # LLM API keys
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    kimi_api_key: str = ""  # Moonshot AI

    # Database
    database_url: str = "sqlite+aiosqlite:///data/xspider.db"

    # Scraping settings
    max_concurrent_requests: int = 5
    request_delay_ms: int = 1000
    max_followings_per_user: int = 500
    crawl_depth: int = 2

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "console"

    # Paths
    data_dir: Path = Path("data")
    cache_dir: Path = Path("data/cache")
    exports_dir: Path = Path("data/exports")

    @field_validator("twitter_tokens", mode="before")
    @classmethod
    def parse_twitter_tokens(cls, v: Any) -> list[TwitterToken]:
        """Parse Twitter tokens from JSON string or list."""
        if isinstance(v, str):
            if not v.strip() or v == "[]":
                return []
            try:
                parsed = json.loads(v)
                return [TwitterToken(**t) for t in parsed]
            except json.JSONDecodeError:
                return []
        if isinstance(v, list):
            return [TwitterToken(**t) if isinstance(t, dict) else t for t in v]
        return []

    @field_validator("proxy_urls", mode="before")
    @classmethod
    def parse_proxy_urls(cls, v: Any) -> list[str]:
        """Parse proxy URLs from JSON string or list."""
        if isinstance(v, str):
            if not v.strip() or v == "[]":
                return []
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v if isinstance(v, list) else []

    def ensure_dirs(self) -> None:
        """Create required directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    settings = Settings()
    settings.ensure_dirs()
    return settings
