import os
import secrets
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.engine import make_url


engine = None
unit_only = False


def validate_test_database_url(value: str) -> str:
    """Refuse any integration target that is not a PostgreSQL ``*_test`` DB."""
    try:
        url = make_url(value)
    except Exception:
        raise RuntimeError("TEST_DATABASE_URL is not a valid database URL") from None
    if url.drivername != "postgresql+asyncpg":
        raise RuntimeError("TEST_DATABASE_URL must use postgresql+asyncpg")
    if not (url.database or "").endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL database name must end with '_test'")
    return value


def _unit_only_invocation(config: pytest.Config) -> bool:
    """Recognize a test-path-only invocation before importing test modules."""
    unit_root = Path(__file__).resolve().parent / "unit"
    selected_paths = []
    for argument in config.args:
        path_argument = argument.split("::", 1)[0]
        if path_argument.startswith("-"):
            continue
        candidate = Path(path_argument)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        selected_paths.append(candidate.resolve())
    return bool(selected_paths) and all(
        path == unit_root or unit_root in path.parents for path in selected_paths
    )


def pytest_configure(config: pytest.Config) -> None:
    """Require service configuration only when collecting service-backed tests."""
    global engine, unit_only
    unit_only = _unit_only_invocation(config)
    if unit_only:
        for key in tuple(os.environ):
            if key.startswith(
                (
                    "DATABASE",
                    "TEST_DATABASE",
                    "TEST_POSTGRES",
                    "TEST_REDIS",
                    "AUTH_",
                    "REDIS",
                )
            ) or key in {"ENVIRONMENT", "LOG_LEVEL"}:
                os.environ.pop(key, None)

        import app.core.config as application_config

        def reject_ambient_settings() -> None:
            raise AssertionError(
                "unit tests must construct Settings with _env_file=None"
            )

        application_config.get_settings = reject_ambient_settings
        return

    test_database_url = os.getenv("TEST_DATABASE_URL")
    if not test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set; tests refuse to truncate DATABASE_URL"
        )
    validate_test_database_url(test_database_url)

    # Test modules are imported after pytest_configure. Point the application at
    # the validated disposable database and generate process-local test secrets.
    os.environ["DATABASE_URL"] = test_database_url
    os.environ["ENVIRONMENT"] = "test"
    os.environ["AUTH_JWT_SECRET"] = secrets.token_urlsafe(48)
    os.environ["AUTH_RATE_LIMIT_SECRET"] = secrets.token_urlsafe(48)
    os.environ["AUTH_TRUSTED_ORIGINS"] = '["http://localhost:3000"]'
    os.environ["AUTH_COOKIE_SECURE"] = "false"
    # Explicit test infrastructure only; never read developer Redis from .env.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from test_support.redis_environment import redis_environment

    os.environ.update(redis_environment(os.environ))

    sync_url = make_url(test_database_url).set(drivername="postgresql+psycopg")
    engine = create_engine(sync_url)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Release the synchronous fixture pool when the integration run ends."""
    if engine is not None:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_database() -> None:
    """Tests use the PostgreSQL schema prepared by Alembic, not SQLite."""
    if engine is None:
        yield
        return

    def truncate() -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE audit_entries, restaurant_assignments, memberships, "
                    "organizations, auth_rate_limit_buckets, auth_refresh_tokens, "
                    "auth_sessions, users, order_items, orders, menu_items, menus, "
                    "restaurants RESTART IDENTITY CASCADE"
                )
            )

    truncate()
    yield
    truncate()


@pytest.fixture
def unit_isolation_state() -> tuple[bool, object]:
    return unit_only, engine


@pytest.fixture
def test_database_url_validator():
    return validate_test_database_url


@pytest.fixture
def auth_user() -> dict[str, str]:
    """Provision a real account; HTTP tests never bypass the auth dependency."""
    import asyncio
    from uuid import uuid4

    from app.modules.auth.security import hash_password

    if engine is None:
        raise RuntimeError("auth_user requires the PostgreSQL integration layer")

    account = {
        "id": str(uuid4()),
        "email": "operator@example.test",
        "password": "A long test password with spaces",  # pragma: allowlist secret
    }
    password_hash = asyncio.run(hash_password(account["password"]))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, email, password_hash, status) "
                "VALUES (:id, :email, :password_hash, 'active')"
            ),
            {**account, "password_hash": password_hash},
        )
        organization_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO organizations (id,name,slug) VALUES (:id,'Test workspace','test-workspace')"
            ),
            {"id": organization_id},
        )
        connection.execute(
            text(
                "INSERT INTO memberships (id,user_id,organization_id,role) VALUES (:id,:user,:org,'OWNER')"
            ),
            {"id": str(uuid4()), "user": account["id"], "org": organization_id},
        )
        account["organization_id"] = organization_id
    return account


@pytest.fixture
def owner_principal(auth_user):
    from uuid import UUID, uuid4
    from app.modules.auth.domain.principal import AuthenticatedPrincipal

    return AuthenticatedPrincipal(
        UUID(auth_user["id"]), auth_user["email"], "active", uuid4()
    )


@pytest.fixture
def authenticated_client(auth_user):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client.headers.update(
            {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
        )
        response = client.post(
            "/auth/login",
            json={
                "email": auth_user["email"],
                "password": auth_user["password"],
            },
        )
        assert response.status_code == 200, response.text
        yield client
