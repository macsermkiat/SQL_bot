"""
Configuration management via environment variables.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM settings
    anthropic_api_key: str = Field(
        ...,
        description="Anthropic API key for Claude",
    )
    claude_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model to use",
    )

    # Database settings
    database_url: str | None = Field(
        default=None,
        description="Full database URL (takes precedence over individual vars)",
    )
    db_host: str = Field(default="localhost", description="Database host")
    db_port: int = Field(default=5432, description="Database port")
    db_name: str = Field(default="kcmh", description="Database name")
    db_user: str = Field(default="readonly", description="Database user")
    db_password: str = Field(default="", description="Database password")

    # Safety settings
    sql_statement_timeout_ms: int = Field(
        default=15000,
        description="SQL statement timeout in milliseconds",
    )
    sql_max_rows: int = Field(
        default=2000,
        description="Maximum rows returned by non-aggregate queries",
    )

    # Authentication settings
    secret_key: str = Field(
        default="change-me-to-a-random-string-at-least-32-chars",
        description="Secret key for signing session cookies",
    )
    session_cookie_name: str = Field(
        default="kcmh_session",
        description="Name of the session cookie",
    )
    session_max_age: int = Field(
        default=28800,
        description="Session max age in seconds (default 8 hours)",
    )
    users_file: str = Field(
        default="usr/ID.csv",
        description="Path to CSV file with user credentials",
    )
    super_users_file: str = Field(
        default="config/super_users.json",
        description="Path to JSON file with super user email list",
    )

    # Paths
    base_dir: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent,
        description="Base directory of the application",
    )

    @computed_field
    @property
    def db_url(self) -> str:
        """Get database URL, preferring DATABASE_URL if set."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @computed_field
    @property
    def schema_dir(self) -> Path:
        return self.base_dir / "schema"

    @computed_field
    @property
    def catalog_path(self) -> Path:
        return self.base_dir / "out" / "catalog.json"

    @computed_field
    @property
    def concepts_path(self) -> Path:
        return self.base_dir / "schema" / "concepts.yaml"

    @computed_field
    @property
    def users_csv_path(self) -> Path:
        return self.base_dir / self.users_file

    @computed_field
    @property
    def super_users_path(self) -> Path:
        return self.base_dir / self.super_users_file

    @computed_field
    @property
    def templates_dir(self) -> Path:
        return self.base_dir / "app" / "templates"

    @computed_field
    @property
    def static_dir(self) -> Path:
        return self.base_dir / "app" / "static"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
