"""Verify inventory migrations and optional suites in newly created databases only."""

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PREVIOUS_HEAD = "b37a6d91e204"  # pragma: allowlist secret


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--run-browser", action="store_true")
    args = parser.parse_args()
    load_dotenv(BACKEND / ".env")
    source = os.environ.get("TEST_DATABASE_URL", "")
    if not source or not (make_url(source).database or "").endswith("_test"):
        raise SystemExit("TEST_DATABASE_URL ending in _test is required.")
    url = make_url(source).set(drivername="postgresql")
    with psycopg.connect(
        url.set(database="postgres").render_as_string(hide_password=False),
        autocommit=True,
        connect_timeout=5,
    ) as admin:
        for scenario in ("upgrade", "clean"):
            database = f"restaurantos_inventory_{scenario}_{uuid4().hex[:10]}_test"
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
            )
            db_url = url.set(database=database)
            async_url = db_url.set(drivername="postgresql+asyncpg").render_as_string(
                hide_password=False
            )
            environment = {
                **os.environ,
                "DATABASE_URL": async_url,
                "TEST_DATABASE_URL": async_url,
                "ENVIRONMENT": "test",
                "AUTH_JWT_SECRET": secrets.token_urlsafe(48),
                "AUTH_RATE_LIMIT_SECRET": secrets.token_urlsafe(48),
            }

            def run(*command: str, env: dict[str, str] = environment) -> None:
                subprocess.run(
                    [sys.executable, *command], cwd=BACKEND, env=env, check=True
                )

            def snapshot(target: URL = db_url) -> list:
                with psycopg.connect(
                    target.render_as_string(hide_password=False)
                ) as db:
                    return db.execute(
                        "SELECT r.name, o.status, o.total, i.item_name, i.quantity, "
                        "i.unit_price, i.line_total FROM restaurants r "
                        "JOIN orders o ON o.restaurant_id=r.id "
                        "JOIN order_items i ON i.order_id=o.order_id"
                    ).fetchall()

            try:
                if scenario == "upgrade":
                    run("-m", "alembic", "upgrade", PREVIOUS_HEAD)
                    with psycopg.connect(
                        db_url.render_as_string(hide_password=False)
                    ) as db:
                        organization = uuid4()
                        db.execute(
                            "INSERT INTO organizations (id,name,slug) VALUES (%s,'Inventory migration','inventory-migration')",
                            (organization,),
                        )
                        db.execute(
                            "INSERT INTO restaurants (id,organization_id,name,created_at,updated_at) VALUES (1,%s,'Existing restaurant',now(),now())",
                            (organization,),
                        )
                        db.execute(
                            "INSERT INTO orders (order_id,restaurant_id,status,subtotal,total,created_at,updated_at) VALUES (1,1,'COMPLETED',25,25,now(),now())"
                        )
                        db.execute(
                            "INSERT INTO order_items (order_item_id,order_id,item_name,quantity,unit_price,line_total) VALUES (1,1,'Historical meal',2,12.5,25)"
                        )
                    before = snapshot()
                run("-m", "alembic", "upgrade", "head")
                run("-m", "alembic", "check")
                if scenario == "upgrade":
                    assert snapshot() == before
                    run("-m", "alembic", "downgrade", PREVIOUS_HEAD)
                    assert snapshot() == before
                    run("-m", "alembic", "upgrade", "head")
                    run("-m", "alembic", "check")
                    assert snapshot() == before
                else:
                    if args.run_tests:
                        run("-m", "pytest")
                    if args.run_browser:
                        run(str(ROOT / "scripts" / "run-browser-tests.py"))
                    run("-m", "alembic", "check")
                print(f"PASS: inventory {scenario} scenario", flush=True)
            finally:
                # The name is generated above and created by this invocation.
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(database)
                    )
                )


if __name__ == "__main__":
    main()
