"""Rehearse the tenancy schema only in databases created by this invocation."""

import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

from dotenv import load_dotenv
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

backend = Path(__file__).resolve().parents[1] / "backend"
load_dotenv(backend / ".env")
source = os.environ.get("TEST_DATABASE_URL", "")
if not source or not (make_url(source).database or "").endswith("_test"):
    raise SystemExit("TEST_DATABASE_URL ending in _test is required.")
url = make_url(source).set(drivername="postgresql")
environment = {
    **os.environ,
    "ENVIRONMENT": "test",
    "AUTH_JWT_SECRET": secrets.token_urlsafe(48),
    "AUTH_RATE_LIMIT_SECRET": secrets.token_urlsafe(48),
}
previous_head = "72bd03a1f901"  # pragma: allowlist secret
schema_head = "83c7e1b4a902"  # pragma: allowlist secret


def database_environment(database: str) -> dict[str, str]:
    database_url = url.set(drivername="postgresql+asyncpg", database=database)
    value = database_url.render_as_string(hide_password=False)
    return {**environment, "DATABASE_URL": value, "TEST_DATABASE_URL": value}


def migrate(database: str, *arguments: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=backend,
        env=database_environment(database),
        check=True,
    )


def history(database: str) -> tuple:
    with psycopg.connect(
        url.set(database=database).render_as_string(hide_password=False)
    ) as db:
        return db.execute(
            "SELECT r.name,o.status,o.total,i.item_name,i.quantity,i.unit_price,i.line_total "
            "FROM restaurants r JOIN orders o ON r.id=o.restaurant_id "
            "JOIN order_items i ON o.order_id=i.order_id"
        ).fetchone()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run the full backend suite in the clean disposable database",
    )
    arguments = parser.parse_args()
    with psycopg.connect(
        url.set(database="postgres").render_as_string(hide_password=False),
        autocommit=True,
    ) as admin:
        for scenario in ("clean", "upgrade"):
            database = f"restaurantos_m4_{scenario}_{uuid4().hex[:10]}_test"
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
            )
            try:
                if scenario == "upgrade":
                    migrate(database, "upgrade", previous_head)
                    with psycopg.connect(
                        url.set(database=database).render_as_string(hide_password=False)
                    ) as db:
                        db.execute(
                            "INSERT INTO restaurants (id,name,created_at,updated_at) VALUES (1,'Legacy branch',now(),now())"
                        )
                        db.execute(
                            "INSERT INTO orders (order_id,restaurant_id,status,subtotal,total,created_at,updated_at) VALUES (1,1,'COMPLETED',25,25,now(),now())"
                        )
                        db.execute(
                            "INSERT INTO order_items (order_item_id,order_id,item_name,quantity,unit_price,line_total) VALUES (1,1,'Historical noodles',2,12.5,25)"
                        )
                        db.execute(
                            "INSERT INTO users (id,email,password_hash) VALUES (%s,'legacy@example.test','migration-test-only')",
                            (uuid4(),),
                        )
                    before = history(database)
                migrate(database, "upgrade", schema_head)
                migrate(database, "check")
                with psycopg.connect(
                    url.set(database=database).render_as_string(hide_password=False)
                ) as db:
                    assert db.execute(
                        "SELECT count(*) FROM organizations WHERE slug='restaurantos-development'"
                    ).fetchone() == (1,)
                    assert db.execute(
                        "SELECT count(*) FROM memberships"
                    ).fetchone() == (0,)
                    assert db.execute(
                        "SELECT count(*) FROM restaurants WHERE organization_id IS NULL"
                    ).fetchone() == (0,)
                    assert db.execute(
                        "SELECT count(*) FROM restaurants r JOIN organizations g ON g.id=r.organization_id WHERE g.slug='restaurantos-development'"
                    ).fetchone() == ((1,) if scenario == "upgrade" else (0,))
                if scenario == "upgrade":
                    assert history(database) == before
                    migrate(database, "downgrade", previous_head)
                    assert history(database) == before
                    migrate(database, "upgrade", schema_head)
                    migrate(database, "check")
                    assert history(database) == before
                    with psycopg.connect(
                        url.set(database=database).render_as_string(hide_password=False)
                    ) as db:
                        assert db.execute(
                            "SELECT email,password_hash,status FROM users"
                        ).fetchone() == (
                            "legacy@example.test",
                            "migration-test-only",
                            "active",
                        )
                elif arguments.run_tests:
                    subprocess.run(
                        [sys.executable, "-m", "pytest"],
                        cwd=backend,
                        env=database_environment(database),
                        check=True,
                    )
                    migrate(database, "check")
                print(f"PASS: {scenario} tenancy migration scenario", flush=True)
            finally:
                # Never remove an existing/shared database, only this invocation's DB.
                admin.execute(
                    sql.SQL("DROP DATABASE {}").format(sql.Identifier(database))
                )


if __name__ == "__main__":
    main()
