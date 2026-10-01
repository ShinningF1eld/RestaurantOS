import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize("field", ["AUTH_JWT_SECRET", "AUTH_RATE_LIMIT_SECRET"])
def test_auth_secret_is_required(monkeypatch, field):
    monkeypatch.delenv(field, raising=False)
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "changes",
    [
        {"auth_jwt_secret": "short"},  # pragma: allowlist secret
        {"auth_rate_limit_secret": "short"},  # pragma: allowlist secret
        {"auth_access_seconds": 0},
        {"auth_session_seconds": -1},
        {"auth_login_email_limit": 0},
        {"auth_refresh_window_seconds": 0},
        {"auth_trusted_origins": ["*"]},
        {"auth_trusted_origins": ["https://example.test/path"]},
        {"auth_trusted_origins": ["https://user@example.test"]},
        {"auth_trusted_origins": []},
        {"environment": "production", "auth_cookie_secure": False},
        {
            "environment": "production",
            "auth_cookie_secure": True,
            "auth_trusted_origins": ["http://example.test"],
        },
        {
            "environment": "production",
            "auth_cookie_secure": True,
            "auth_trusted_origins": ["https://example.test"],
            "database_echo": True,
        },
    ],
)
def test_insecure_or_invalid_auth_configuration_is_rejected(changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **changes)


def test_production_accepts_secure_exact_origin():
    settings = Settings(
        _env_file=None,
        environment="production",
        auth_cookie_secure=True,
        auth_trusted_origins=["https://example.test"],
    )
    assert settings.auth_cookie_secure
    assert settings.auth_jwt_secret.get_secret_value() not in repr(settings)
    assert settings.auth_rate_limit_secret.get_secret_value() not in repr(settings)
