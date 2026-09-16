import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None)


def test_settings_normalizes_typed_environment_values() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:pass@localhost:5432/restaurantos",  # pragma: allowlist secret
        environment="TEST",
        log_level="debug",
        database_echo=True,
    )

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.database_echo is True


def test_settings_rejects_non_async_postgresql_database_url() -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+asyncpg"):
        Settings(
            _env_file=None,
            database_url="sqlite:///restaurantos.db",
        )
