"""Create uniquely named, guarded PostgreSQL databases for test runners.

This module intentionally does not load dotenv files or fall back to
``DATABASE_URL``. Callers must opt in with a dedicated ``TEST_DATABASE_URL``.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Iterator, Mapping
from collections.abc import Set as AbstractSet
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})
_DATABASE_PREFIX = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@dataclass(frozen=True, slots=True)
class TestDatabase:
    """Connection details for one allocated test database."""

    name: str
    async_url: str = field(repr=False)
    sync_url: str = field(repr=False)

    def environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """Return an isolated app environment for Alembic, tests, or a runner."""

        result = dict(os.environ if base is None else base)
        jwt_secret = secrets.token_urlsafe(48)
        rate_limit_secret = secrets.token_urlsafe(48)
        while rate_limit_secret == jwt_secret:
            rate_limit_secret = secrets.token_urlsafe(48)
        result.update(
            {
                "DATABASE_URL": self.async_url,
                "TEST_DATABASE_URL": self.async_url,
                "ENVIRONMENT": "test",
                "AUTH_COOKIE_SECURE": "false",
                "AUTH_TRUSTED_ORIGINS": '["http://localhost:3000"]',
                "AUTH_JWT_SECRET": jwt_secret,
                "AUTH_RATE_LIMIT_SECRET": rate_limit_secret,
            }
        )
        return result


def read_test_url(
    environ: Mapping[str, str] | None = None,
    *,
    allowed_hosts: AbstractSet[str] = DEFAULT_ALLOWED_HOSTS,
) -> URL:
    """Read and validate only ``TEST_DATABASE_URL`` from the supplied env."""

    variables = os.environ if environ is None else environ
    raw_url = variables.get("TEST_DATABASE_URL", "").strip()
    if not raw_url:
        raise ValueError(
            "Set TEST_DATABASE_URL to a dedicated PostgreSQL *_test database"
        )

    try:
        url = make_url(raw_url)
    except (ArgumentError, ValueError):
        raise ValueError(
            "TEST_DATABASE_URL is not a valid SQLAlchemy database URL"
        ) from None

    if url.drivername not in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}:
        raise ValueError("TEST_DATABASE_URL must use PostgreSQL")
    if not url.database or not url.database.endswith("_test"):
        raise ValueError("TEST_DATABASE_URL database name must end in _test")
    host = (url.host or "").lower().rstrip(".")
    normalized_allowed = {candidate.lower().rstrip(".") for candidate in allowed_hosts}
    if not host or host not in normalized_allowed:
        allowed = ", ".join(sorted(normalized_allowed))
        raise ValueError(f"TEST_DATABASE_URL host must be one of: {allowed}")

    return url


def _parse_source_url(
    test_url: URL | str | None, allowed_hosts: AbstractSet[str]
) -> URL:
    if test_url is None:
        return read_test_url(allowed_hosts=allowed_hosts)
    if isinstance(test_url, URL):
        raw = test_url.render_as_string(hide_password=False)
    else:
        raw = test_url
    return read_test_url({"TEST_DATABASE_URL": raw}, allowed_hosts=allowed_hosts)


@contextmanager
def disposable_database(
    *,
    prefix: str = "restaurantos_m6",
    test_url: URL | str | None = None,
    allowed_hosts: AbstractSet[str] = DEFAULT_ALLOWED_HOSTS,
) -> Iterator[TestDatabase]:
    """Create and always drop a unique ``*_test`` database on an allowed host.

    The configured database is used only as a connection template. This helper
    connects to PostgreSQL's maintenance database, creates a new random name,
    and drops only that allocated name, including when the caller raises.
    """

    if not _DATABASE_PREFIX.fullmatch(prefix):
        raise ValueError(
            "Database prefix must be lowercase letters, digits, and underscores"
        )

    source = _parse_source_url(test_url, allowed_hosts)
    name = f"{prefix[:25]}_{uuid4().hex}_test"
    admin_url = source.set(drivername="postgresql", database="postgres")
    connection_string = admin_url.render_as_string(hide_password=False)

    with psycopg.connect(
        connection_string, autocommit=True, connect_timeout=5
    ) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            database_url = source.set(database=name)
            database = TestDatabase(
                name=name,
                async_url=database_url.set(
                    drivername="postgresql+asyncpg"
                ).render_as_string(hide_password=False),
                sync_url=database_url.set(drivername="postgresql").render_as_string(
                    hide_password=False
                ),
            )
            yield database
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )
            remaining = admin.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (name,)
            ).fetchone()
            if remaining is not None:
                raise RuntimeError(f"Disposable database cleanup failed for {name}")
