import os
import secrets

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

load_dotenv()
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set; tests refuse to truncate DATABASE_URL"
    )

database_name = make_url(TEST_DATABASE_URL).database or ""
if not database_name.endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL database name must end with '_test'")

# Application modules are imported only after pytest loads this conftest. Point
# the application at the same isolated database used by the cleanup fixture.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["AUTH_JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["AUTH_RATE_LIMIT_SECRET"] = secrets.token_urlsafe(48)
os.environ["AUTH_TRUSTED_ORIGINS"] = '["http://localhost:3000"]'
os.environ["AUTH_COOKIE_SECURE"] = "false"

sync_url = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg://")
engine = create_engine(sync_url)


@pytest.fixture(autouse=True)
def clean_database() -> None:
    """Tests use the PostgreSQL schema prepared by Alembic, not SQLite."""

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
def auth_user() -> dict[str, str]:
    """Provision a real account; HTTP tests never bypass the auth dependency."""
    import asyncio
    from uuid import uuid4

    from app.modules.auth.security import hash_password

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
