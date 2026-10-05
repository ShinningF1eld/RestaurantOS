"""Rehearse additive migrations and verify Milestone 5 on disposable local DBs."""

import argparse
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
INVENTORY_HEAD = "c48b7e02f315"  # pragma: allowlist secret
RECIPE_HEAD = "d57c8f13a426"  # pragma: allowlist secret
ORDER_HEAD = "e68d9a24b537"  # pragma: allowlist secret


def run(*command: str, env: dict[str, str], cwd: Path = BACKEND) -> None:
    subprocess.run(list(command), cwd=cwd, env=env, check=True)


def snapshot(db: psycopg.Connection) -> list:
    statements = [
        "SELECT id,name FROM restaurants ORDER BY id",
        "SELECT menu_id,restaurant_id,name FROM menus ORDER BY menu_id",
        "SELECT menu_item_id,menu_id,name,price,is_available FROM menu_items ORDER BY menu_item_id",
        "SELECT order_id,restaurant_id,status,total FROM orders ORDER BY order_id",
        "SELECT order_id,item_name,quantity,unit_price,line_total FROM order_items ORDER BY order_item_id",
        "SELECT id,restaurant_id,name,unit,reorder_threshold,is_active FROM inventory_ingredients ORDER BY id",
        "SELECT ingredient_id,quantity,version FROM inventory_balances ORDER BY ingredient_id",
        "SELECT ingredient_id,kind,quantity_delta,balance_after,version_after,reason FROM inventory_movements ORDER BY id",
    ]
    return [db.execute(statement).fetchall() for statement in statements]


def seed_legacy(db: psycopg.Connection) -> None:
    org = uuid4()
    db.execute("INSERT INTO organizations(id,name,slug) VALUES(%s,'Migration branch','m5-migration')", (org,))
    db.execute("INSERT INTO restaurants(id,organization_id,name,created_at,updated_at) VALUES(1,%s,'Existing branch',now(),now())", (org,))
    db.execute("INSERT INTO menus(menu_id,restaurant_id,name) VALUES(1,1,'Existing menu')")
    db.execute("INSERT INTO menu_items(menu_item_id,menu_id,name,price,is_available) VALUES(1,1,'Historical chicken',25,true)")
    for ident, state in [(1, "ACCEPTED"), (2, "COMPLETED")]:
        db.execute("INSERT INTO orders(order_id,restaurant_id,status,subtotal,total,created_at,updated_at) VALUES(%s,1,%s,50,50,now(),now())", (ident, state))
        db.execute("INSERT INTO order_items(order_item_id,order_id,menu_item_id,item_name,quantity,unit_price,line_total) VALUES(%s,%s,1,'Historical chicken',2,25,50)", (ident, ident))
    db.execute("INSERT INTO inventory_ingredients(id,restaurant_id,name,normalized_name,unit,reorder_threshold,is_active,created_at,updated_at) VALUES(1,1,'Chicken','chicken','g',100,true,now(),now())")
    db.execute("INSERT INTO inventory_balances(ingredient_id,quantity,version) VALUES(1,1000,1)")
    db.execute("INSERT INTO inventory_movements(ingredient_id,kind,quantity_delta,balance_after,version_after,reason,idempotency_key,request_fingerprint,occurred_at) VALUES(1,'opening',1000,1000,1,'Legacy opening','legacy-opening',%s,now())", ("0" * 64,))


def verify_history_downgrade_guard(db_url: str, env: dict[str, str]) -> None:
    """A rollback must refuse to erase consumption and submission history."""
    with psycopg.connect(db_url) as db:
        db.execute("UPDATE orders SET inventory_processed=true WHERE order_id=1")
        db.execute("UPDATE inventory_balances SET quantity=990,version=2 WHERE ingredient_id=1")
        db.execute("INSERT INTO inventory_movements(ingredient_id,kind,quantity_delta,balance_after,version_after,reason,order_id,occurred_at) VALUES(1,'consumption',-10,990,2,'Migration accepted order',1,now())")
        db.execute("INSERT INTO order_submissions(restaurant_id,idempotency_key,order_id,request_fingerprint,response_snapshot,created_at) VALUES(1,'migration-order',1,%s,'{}',now())", ("0" * 64,))
        before = snapshot(db)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", RECIPE_HEAD],
        cwd=BACKEND, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0 and "Cannot downgrade" in result.stderr
    with psycopg.connect(db_url) as db:
        assert snapshot(db) == before
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == ORDER_HEAD
        assert db.execute("SELECT inventory_processed FROM orders WHERE order_id=1").fetchone()[0]
        assert db.execute("SELECT count(*) FROM order_submissions").fetchone()[0] == 1
    print("PASS: downgrade refuses to erase order inventory history", flush=True)


@contextmanager
def frontend_copy():
    """Build elsewhere so an active developer server and its build stay intact."""
    folder = Path(tempfile.mkdtemp(prefix=".m5-browser-", dir=ROOT)).resolve()
    assert folder.parent == ROOT.resolve() and folder.name.startswith(".m5-browser-")
    frontend = folder / "frontend"
    junction = frontend / "node_modules"
    try:
        for directory, directories, filenames in os.walk(ROOT / "frontend"):
            directories[:] = [name for name in directories if name not in {"node_modules", ".next", "test-results", "playwright-report", ".git"}]
            for filename in filenames:
                source = Path(directory) / filename
                relative = source.relative_to(ROOT / "frontend")
                if source.name.startswith(".env"):
                    continue
                target = frontend / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        dependencies = ROOT / "frontend" / "node_modules"
        # A staged source snapshot may share its parent's installed dependencies.
        if not dependencies.exists():
            dependencies = Path(os.environ["M5_FRONTEND_DEPENDENCIES"])
        if os.name == "nt":
            run("cmd", "/c", "mklink", "/J", str(junction), str(dependencies), env=dict(os.environ), cwd=ROOT)
        else:
            junction.symlink_to(dependencies, target_is_directory=True)
        config = frontend / "next.config.ts"
        shutil.move(config, frontend / "next.config.base.ts")
        config.write_text(
            'import config from "./next.config.base";\n'
            'export default { ...config, turbopack: { ...config.turbopack, root: process.env.M5_SOURCE_ROOT } };\n',
            encoding="utf-8",
        )
        yield frontend
    finally:
        if junction.exists():
            if os.name == "nt":
                os.rmdir(junction)
            else:
                junction.unlink()
        assert folder.parent == ROOT.resolve() and folder.name.startswith(".m5-browser-")
        shutil.rmtree(folder)


def browser(env: dict[str, str], grep: str | None) -> None:
    for port in (8101, 3101):
        with socket.socket() as probe:
            if probe.connect_ex(("localhost", port)) == 0:
                raise RuntimeError(f"Audit port {port} is occupied")
    env = {
        **env,
        "NEXT_PUBLIC_API_URL": "http://localhost:8101",
        "API_URL": "http://localhost:8101",
        "AUTH_COOKIE_SECURE": "false",
        "AUTH_TRUSTED_ORIGINS": '["http://localhost:3101"]',
        "PLAYWRIGHT_BASE_URL": "http://localhost:3101",
        "PLAYWRIGHT_WEB_PORT": "3101",
        "PLAYWRIGHT_PYTHON": sys.executable,
        "PYTHONPATH": str(BACKEND),
        "M5_SOURCE_ROOT": os.environ.get("M5_SOURCE_ROOT", str(ROOT)),
    }
    env.pop("PLAYWRIGHT_EXTERNAL_SERVER", None)
    for key in ("AUTH_LOGIN_EMAIL_LIMIT", "AUTH_LOGIN_IP_LIMIT", "AUTH_REFRESH_FAMILY_LIMIT", "AUTH_REFRESH_IP_LIMIT", "AUTH_ACCESS_SECONDS", "AUTH_SESSION_SECONDS"):
        env.pop(key, None)
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required")
    with frontend_copy() as frontend:
        run(npm, "run", "build", env=env, cwd=frontend)
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
            api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8101", "--no-proxy-headers"], cwd=BACKEND, env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if api.poll() is not None:
                        raise RuntimeError("Audit API stopped before startup")
                    try:
                        with urlopen("http://localhost:8101/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except (URLError, TimeoutError):
                        time.sleep(0.2)
                else:
                    raise RuntimeError("Audit API did not become healthy")
                command = [npm, "run", "test:e2e"]
                if grep:
                    command.extend(["--", "--grep", grep])
                run(*command, env=env, cwd=frontend)
            except Exception:
                log.seek(0)
                print(log.read()[-8000:], file=sys.stderr)
                raise
            finally:
                api.terminate()
                try:
                    api.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    api.kill()
                    api.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", nargs="*", help="Run pytest; no paths runs the complete suite")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--browser-grep")
    parser.add_argument("--revision", default="head")
    args = parser.parse_args()
    load_dotenv(BACKEND / ".env")
    raw = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    url = make_url(raw).set(drivername="postgresql")
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("This rehearsal requires a configured local PostgreSQL server")
    with psycopg.connect(url.set(database="postgres").render_as_string(hide_password=False), autocommit=True, connect_timeout=5) as admin:
        for previous in (INVENTORY_HEAD, None):
            database = f"restaurantos_m5_{uuid4().hex[:10]}_test"
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            async_url = url.set(drivername="postgresql+asyncpg", database=database).render_as_string(hide_password=False)
            env = {**os.environ, "DATABASE_URL": async_url, "TEST_DATABASE_URL": async_url, "ENVIRONMENT": "test", "AUTH_JWT_SECRET": secrets.token_urlsafe(48), "AUTH_RATE_LIMIT_SECRET": secrets.token_urlsafe(48)}
            try:
                if previous:
                    run(sys.executable, "-m", "alembic", "upgrade", previous, env=env)
                    with psycopg.connect(url.set(database=database).render_as_string(hide_password=False)) as db:
                        seed_legacy(db)
                        before = snapshot(db)
                    run(sys.executable, "-m", "alembic", "upgrade", RECIPE_HEAD, env=env)
                run(sys.executable, "-m", "alembic", "upgrade", args.revision, env=env)
                run(sys.executable, "-m", "alembic", "check", env=env)
                if previous:
                    with psycopg.connect(url.set(database=database).render_as_string(hide_password=False)) as db:
                        assert snapshot(db) == before
                        assert not db.execute("SELECT inventory_tracking FROM menu_items").fetchone()[0]
                        if args.revision != RECIPE_HEAD:
                            assert all(not row[0] for row in db.execute("SELECT inventory_processed FROM orders").fetchall())
                    run(sys.executable, "-m", "alembic", "downgrade", previous, env=env)
                    run(sys.executable, "-m", "alembic", "upgrade", args.revision, env=env)
                    run(sys.executable, "-m", "alembic", "check", env=env)
                    with psycopg.connect(url.set(database=database).render_as_string(hide_password=False)) as db:
                        assert snapshot(db) == before
                    if args.revision != RECIPE_HEAD:
                        verify_history_downgrade_guard(
                            url.set(database=database).render_as_string(hide_password=False), env
                        )
                else:
                    if args.tests is not None:
                        run(sys.executable, "-m", "pytest", *args.tests, env=env)
                    if args.browser:
                        browser(env, args.browser_grep)
                print(f"PASS: Milestone 5 {'previous-head' if previous else 'clean'} verification", flush=True)
            finally:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


if __name__ == "__main__":
    main()
