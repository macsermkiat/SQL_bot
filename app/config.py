"""
Configuration management via environment variables.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SECRET_KEY = "change-me-to-a-random-string-at-least-32-chars"


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
        default="claude-sonnet-4-6",
        description="Claude model to use (the executor model)",
    )

    # Advisor tool (beta: advisor-tool-2026-03-01) — pairs the executor
    # with a stronger advisor model for strategic mid-generation guidance.
    advisor_enabled: bool = Field(
        default=False,
        description="Enable the advisor tool for SQL generation",
    )
    advisor_model: str = Field(
        default="claude-opus-4-6",
        description="Advisor model ID (must be >= executor in capability)",
    )
    advisor_max_uses: int = Field(
        default=2,
        description="Max advisor calls per SQL generation request",
    )
    advisor_backend: Literal["anthropic", "codex"] = Field(
        default="anthropic",
        description="Advisor backend: 'anthropic' uses Claude Opus beta tool, 'codex' uses OpenAI GPT-5.5",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key (required when advisor_backend='codex')",
    )
    codex_model: str = Field(
        default="gpt-5.5",
        description="OpenAI model to use as Codex advisor",
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
        default=180000,
        description="Default SQL statement timeout in milliseconds (3 mins)",
    )
    sql_max_timeout_ms: int = Field(
        default=0,
        description="Maximum SQL statement timeout in milliseconds (unlimit in hard cap)",
    )
    sql_max_rows: int = Field(
        default=2000,
        description="Maximum rows returned by non-aggregate queries",
    )

    # Authentication settings
    app_env: Literal["development", "test", "production"] = Field(
        default="development",
        description="Runtime environment. Production enforces stricter safety checks.",
    )
    secret_key: str = Field(
        default=DEFAULT_SECRET_KEY,
        description="Secret key for signing session cookies",
    )
    secure_cookies: bool = Field(
        default=False,
        description="Set Secure on session cookies. Enable when serving over HTTPS.",
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

    # Supabase logging (optional — logging disabled if unset)
    supabase_url: str | None = Field(
        default=None,
        description="Supabase project URL for query logging",
    )
    supabase_service_key: str | None = Field(
        default=None,
        description="Supabase service_role key for server-side inserts",
    )

    # Notion logging (optional — logging disabled if unset)
    notion_api_key: str | None = Field(
        default=None,
        description="Notion Internal Integration Token for pushing query logs",
    )
    notion_database_id: str | None = Field(
        default=None,
        description="Notion database ID to push query logs to",
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
    def schema_knowledge_path(self) -> Path:
        return self.base_dir / "out" / "schema_knowledge.json"

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

    def validate_runtime_safety(self) -> None:
        """Fail fast on unsafe production configuration."""
        if self.app_env != "production":
            return

        if self.secret_key == DEFAULT_SECRET_KEY or len(self.secret_key) < 32:
            raise RuntimeError(
                "SECRET_KEY must be set to a unique value of at least 32 "
                "characters when APP_ENV=production."
            )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
