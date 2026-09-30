"""Rehearse auth migrations in newly created disposable PostgreSQL databases."""
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
    **os.environ, "ENVIRONMENT": "test",
    "AUTH_JWT_SECRET": secrets.token_urlsafe(48),
    "AUTH_RATE_LIMIT_SECRET": secrets.token_urlsafe(48),
}


def migrate(database: str, *arguments: str) -> None:
    env = {**environment, "DATABASE_URL": url.set(drivername="postgresql+asyncpg", database=database).render_as_string(hide_password=False)}
    subprocess.run([sys.executable, "-m", "alembic", *arguments], cwd=backend, env=env, check=True)


with psycopg.connect(url.set(database="postgres").render_as_string(hide_password=False), autocommit=True) as admin:
    for scenario in ("clean", "upgrade"):
        # Only drop a database successfully created by this invocation.
        database = f"restaurantos_m3_{scenario}_{uuid4().hex[:10]}_test"
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            if scenario == "upgrade":
                migrate(database, "upgrade", "4a1e9a2dc8e4")  # pragma: allowlist secret
                with psycopg.connect(url.set(database=database).render_as_string(hide_password=False)) as fixture:
                    fixture.execute("INSERT INTO restaurants (id,name,created_at,updated_at) VALUES (1,'Migration history',now(),now())")
                    fixture.execute("INSERT INTO orders (order_id,restaurant_id,status,subtotal,total,created_at,updated_at) VALUES (1,1,'COMPLETED',25,25,now(),now())")
                    fixture.execute("INSERT INTO order_items (order_item_id,order_id,item_name,quantity,unit_price,line_total) VALUES (1,1,'Historical noodles',2,12.5,25)")
            migrate(database, "upgrade", "head")
            migrate(database, "check")
            if scenario == "upgrade":
                migrate(database, "downgrade", "4a1e9a2dc8e4")  # pragma: allowlist secret
                migrate(database, "upgrade", "head")
                with psycopg.connect(url.set(database=database).render_as_string(hide_password=False)) as fixture:
                    row = fixture.execute("SELECT r.name,o.status,o.total,i.item_name,i.quantity,i.unit_price,i.line_total FROM restaurants r JOIN orders o ON r.id=o.restaurant_id JOIN order_items i ON o.order_id=i.order_id").fetchone()
                    assert row and row[0:2] == ("Migration history", "COMPLETED") and row[2] == 25 and row[3:] == ("Historical noodles", 2, 12.5, 25), row
            print(f"PASS: {scenario} migration scenario")
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
