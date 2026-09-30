"""Typed, fail-fast configuration for the application boundary."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Environment = Literal["development", "test", "production"]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration loaded from environment variables and an optional ``.env`` file.

    ``database_url`` deliberately has no default: application startup should fail
    early when database configuration is absent rather than opening a partially
    configured service.
    """

    model_config = SettingsConfigDict(
        env_file=_BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(validation_alias="DATABASE_URL")
    environment: Environment = Field(default="development", validation_alias="ENVIRONMENT")
    log_level: LogLevel = Field(default="INFO", validation_alias="LOG_LEVEL")
    database_echo: bool = Field(default=False, validation_alias="DATABASE_ECHO")

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process configuration after validating all declared fields."""

    return Settings()  # type: ignore[call-arg]  # Values are supplied by BaseSettings.
