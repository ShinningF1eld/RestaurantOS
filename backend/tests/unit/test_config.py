import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_requires_database_url(
    monkeypatch: pytest.MonkeyPatch, unit_settings_kwargs
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            _env_file=None,
            auth_jwt_secret=unit_settings_kwargs["auth_jwt_secret"],
            auth_rate_limit_secret=unit_settings_kwargs["auth_rate_limit_secret"],
        )


def test_settings_normalizes_typed_environment_values(unit_settings_kwargs) -> None:
    settings = Settings(
        _env_file=None,
        **unit_settings_kwargs,
        environment="TEST",
        log_level="debug",
        database_echo=True,
    )

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.database_echo is True


def test_settings_rejects_non_async_postgresql_database_url(
    unit_settings_kwargs,
) -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+asyncpg"):
        Settings(
            _env_file=None,
            database_url="sqlite:///restaurantos.db",
            auth_jwt_secret=unit_settings_kwargs["auth_jwt_secret"],
            auth_rate_limit_secret=unit_settings_kwargs["auth_rate_limit_secret"],
        )
