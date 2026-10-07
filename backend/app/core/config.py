"""Typed, fail-fast configuration for the application boundary."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
        hide_input_in_errors=True,
    )

    database_url: str = Field(validation_alias="DATABASE_URL")
    environment: Environment = Field(
        default="development", validation_alias="ENVIRONMENT"
    )
    log_level: LogLevel = Field(default="INFO", validation_alias="LOG_LEVEL")
    database_echo: bool = Field(default=False, validation_alias="DATABASE_ECHO")
    redis_url: SecretStr = Field(default=SecretStr("redis://localhost:6379/0"))
    redis_operation_budget_ms: int = Field(default=100, gt=0, le=100)
    redis_max_connections: int = Field(default=20, gt=0, le=1000)
    redis_test_namespace: str = Field(default="test")
    auth_jwt_secret: SecretStr = Field(validation_alias="AUTH_JWT_SECRET")
    auth_rate_limit_secret: SecretStr = Field(validation_alias="AUTH_RATE_LIMIT_SECRET")
    auth_trusted_origins: list[str] = Field(
        default=["http://localhost:3000"], validation_alias="AUTH_TRUSTED_ORIGINS"
    )
    auth_cookie_secure: bool = Field(
        default=False, validation_alias="AUTH_COOKIE_SECURE"
    )
    auth_jwt_issuer: str = "restaurantos"
    auth_jwt_audience: str = "restaurantos-browser"
    auth_access_seconds: int = Field(default=600, gt=0)
    auth_session_seconds: int = Field(default=604800, gt=0)
    auth_login_email_limit: int = Field(default=5, gt=0)
    auth_login_ip_limit: int = Field(default=30, gt=0)
    auth_login_window_seconds: int = Field(default=900, gt=0)
    auth_refresh_family_limit: int = Field(default=30, gt=0)
    auth_refresh_ip_limit: int = Field(default=120, gt=0)
    auth_refresh_window_seconds: int = Field(default=60, gt=0)
    auth_trusted_proxy_ips: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_auth(self) -> "Settings":
        from urllib.parse import urlsplit

        for secret in (self.auth_jwt_secret, self.auth_rate_limit_secret):
            if len(secret.get_secret_value().encode()) < 32:
                raise ValueError("Auth secrets must contain at least 32 bytes")
            if (
                secret.get_secret_value()
                .lower()
                .startswith(("replace", "change", "example", "placeholder"))
            ):
                raise ValueError(
                    "Generate real auth secrets; placeholders are forbidden"
                )
        if self.auth_jwt_secret == self.auth_rate_limit_secret:
            raise ValueError("Auth secrets must be distinct")
        if not self.auth_jwt_issuer.strip() or not self.auth_jwt_audience.strip():
            raise ValueError("JWT issuer and audience cannot be empty")
        if self.auth_access_seconds > self.auth_session_seconds:
            raise ValueError("Access lifetime cannot exceed absolute session lifetime")
        if not self.auth_trusted_origins:
            raise ValueError("At least one exact trusted origin is required")
        for origin in self.auth_trusted_origins:
            url = urlsplit(origin)
            if (
                url.scheme not in {"http", "https"}
                or not url.netloc
                or url.path
                or url.query
                or url.fragment
                or url.username
                or "*" in origin
            ):
                raise ValueError("Trusted origins must be exact HTTP(S) origins")
        if self.environment == "production" and (
            not self.auth_cookie_secure
            or self.database_echo
            or any(
                not value.startswith("https://") for value in self.auth_trusted_origins
            )
        ):
            raise ValueError(
                "Production requires secure cookies, HTTPS origins and disabled SQL echo"
            )
        return self

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

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        from urllib.parse import urlsplit

        try:
            url = urlsplit(value.get_secret_value())
            valid = (
                url.scheme in {"redis", "rediss"}
                and bool(url.hostname)
                and (url.port is None or 0 < url.port <= 65535)
                and not url.query
                and not url.fragment
                and (not url.path or url.path == "/" or url.path[1:].isdigit())
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("REDIS_URL must be a Redis URL without query overrides")
        return value

    @field_validator("redis_test_namespace")
    @classmethod
    def validate_redis_test_namespace(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value):
            raise ValueError("Redis test namespace must be a safe opaque identifier")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process configuration after validating all declared fields."""

    return Settings()  # type: ignore[call-arg]  # Values are supplied by BaseSettings.
