"""Measure authenticated menu reads against a seeded disposable PostgreSQL DB."""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import hashlib
import json
import math
import os
import platform
import secrets
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import psycopg
import uvicorn
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_support.disposable_postgres import TestDatabase, disposable_database

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPT_VERSION = "1.0.0"
DEFAULT_OUTPUT = ROOT / "artifacts" / "benchmarks"
SCENARIOS = ("menu-list", "menu-items", "mixed-read", "mixed-write")
DEFAULT_CONCURRENCY = (1, 10, 25, 50)
QUERY_COUNT: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar(
    "benchmark_query_count", default=None
)


class QueryCountMiddleware:
    """Count SQL executed during a single real HTTP request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return
        counter = [0]
        token = QUERY_COUNT.set(counter)

        async def add_count_header(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-benchmark-postgres-queries", str(counter[0]).encode())
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, add_count_header)
        finally:
            QUERY_COUNT.reset(token)


def count_statement(*_: Any, **__: Any) -> None:
    counter = QUERY_COUNT.get()
    if counter is not None:
        counter[0] += 1


def percentile(values: list[float], percent: float) -> float:
    """Nearest-rank percentile, expressed in milliseconds by callers."""
    if not values:
        raise ValueError("percentile requires at least one value")
    return sorted(values)[max(0, math.ceil(percent / 100 * len(values)) - 1)]


def parse_int_list(value: str) -> tuple[int, ...]:
    try:
        numbers = tuple(int(item.strip()) for item in value.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(
            "expected comma-separated positive integers"
        ) from None
    if not numbers or any(number < 1 for number in numbers):
        raise argparse.ArgumentTypeError("all values must be positive integers")
    return numbers


def seed_data(database: TestDatabase) -> dict[str, Any]:
    """Seed fixed catalog content and owner authorization, using ORM models."""
    sys.path.insert(0, str(BACKEND))
    import app.db.models  # noqa: F401 - register the complete ORM relationship graph
    from app.modules.auth.repo.models import User
    from app.modules.auth.security import hash_password
    from app.modules.catalog.repo.models import Menu, MenuItem
    from app.modules.inventory.repo.models import Ingredient, InventoryBalance
    from app.modules.recipes.repo.models import RecipeComponent
    from app.modules.restaurants.repo.models import Restaurant
    from app.modules.tenancy.domain.roles import MembershipRole
    from app.modules.tenancy.repo.models import Membership, Organization

    async def seed() -> dict[str, Any]:
        engine = create_async_engine(database.async_url, poolclass=None)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        menu_ids: list[int] = []
        item_ids: list[int] = []
        try:
            password = secrets.token_urlsafe(30)
            password_hash = await hash_password(password)
            async with sessions.begin() as session:
                organization = Organization(
                    name="RestaurantOS Benchmark Organization",
                    slug="restaurantos-benchmark",
                )
                owner = User(
                    email="benchmark-owner@example.test", password_hash=password_hash
                )
                manager = User(
                    email="benchmark-manager@example.test",
                    password_hash=password_hash,
                )
                session.add_all([organization, owner, manager])
                await session.flush()
                restaurant = Restaurant(
                    organization_id=organization.id,
                    name="Deterministic Benchmark Restaurant",
                )
                session.add(restaurant)
                await session.flush()
                session.add(
                    Membership(
                        user_id=owner.id,
                        organization_id=organization.id,
                        role=MembershipRole.OWNER,
                    )
                )
                manager_membership = Membership(
                    user_id=manager.id,
                    organization_id=organization.id,
                    role=MembershipRole.MANAGER,
                )
                session.add(manager_membership)
                await session.flush()
                from app.modules.tenancy.repo.models import RestaurantAssignment

                session.add(
                    RestaurantAssignment(
                        membership_id=manager_membership.id,
                        restaurant_id=restaurant.id,
                        organization_id=organization.id,
                    )
                )
                ingredients = [
                    Ingredient(
                        restaurant_id=restaurant.id,
                        name=f"Benchmark Ingredient {index:02d}",
                        normalized_name=f"benchmark ingredient {index:02d}",
                        unit="g",
                        reorder_threshold=0,
                    )
                    for index in range(4)
                ]
                session.add_all(ingredients)
                await session.flush()
                for ingredient in ingredients:
                    session.add(
                        InventoryBalance(
                            ingredient_id=ingredient.id, quantity=Decimal("5000.000")
                        )
                    )
                for menu_number in range(4):
                    menu = Menu(
                        restaurant_id=restaurant.id,
                        name=f"Benchmark Menu {menu_number + 1:02d}",
                        description=f"Deterministic benchmark menu {menu_number + 1:02d}",
                    )
                    session.add(menu)
                    await session.flush()
                    menu_ids.append(menu.menu_id)
                    for item_number in range(40):
                        tracked = item_number < 10
                        item = MenuItem(
                            menu_id=menu.menu_id,
                            name=f"Menu {menu_number + 1:02d} Item {item_number + 1:02d}",
                            description=f"Deterministic catalog item {menu_number + 1:02d}-{item_number + 1:02d}",
                            price=Decimal(f"{(item_number % 20) + 5}.00"),
                            is_available=True,
                            inventory_tracking=tracked,
                        )
                        session.add(item)
                        await session.flush()
                        item_ids.append(item.menu_item_id)
                        if tracked:
                            session.add(
                                RecipeComponent(
                                    menu_item_id=item.menu_item_id,
                                    ingredient_id=ingredients[item_number % 4].id,
                                    quantity=Decimal("25.000"),
                                )
                            )
            return {
                "restaurant_id": restaurant.id,
                "menu_ids": menu_ids,
                "menu_item_ids": item_ids,
                "email": manager.email,
                "password": password,
            }
        finally:
            await engine.dispose()

    return asyncio.run(seed())


async def wait_for_server(url: str, server: uvicorn.Server) -> None:
    async with httpx.AsyncClient() as client:
        for _ in range(150):
            if server.should_exit:
                raise RuntimeError("API server stopped before startup")
            try:
                response = await client.get(f"{url}/health", timeout=1)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                await asyncio.sleep(0.2)
    raise RuntimeError("API server did not become healthy")


def request_plan(
    scenario: str,
    index: int,
    menu_ids: list[int],
    item_ids: list[int],
    restaurant_id: int,
) -> tuple[str, str, dict[str, Any] | None]:
    if scenario == "menu-list":
        return "GET", f"/restaurants/{restaurant_id}/menus", None
    menu_id = menu_ids[index % len(menu_ids)]
    if scenario == "menu-items":
        return "GET", f"/menus/{menu_id}/items", None
    if scenario == "mixed-read":
        if index % 5 == 0:
            return "GET", f"/restaurants/{restaurant_id}/menus", None
        return "GET", f"/menus/{menu_id}/items", None
    if scenario == "mixed-write" and index % 5 == 0:
        item_id = item_ids[index % len(item_ids)]
        return (
            "PUT",
            f"/menu-items/{item_id}",
            {
                "name": f"Menu Item {item_id:04d}",
                "price": "12.00",
                "is_available": True,
            },
        )
    if scenario == "mixed-write" and index % 5 == 1:
        return (
            "PUT",
            f"/menus/{menu_id}",
            {
                "name": f"Benchmark Menu {menu_id:04d}",
                "description": "Mixed read/write benchmark update",
            },
        )
    return "GET", f"/menus/{menu_id}/items", None


async def measure_scenario(
    client: httpx.AsyncClient,
    *,
    scenario: str,
    requests: int,
    warmup: int,
    concurrency: int,
    menu_ids: list[int],
    item_ids: list[int],
    restaurant_id: int,
) -> dict[str, Any]:
    async def request(index: int) -> tuple[float, int, bool, str]:
        method, path, payload = request_plan(
            scenario, index, menu_ids, item_ids, restaurant_id
        )
        started = time.perf_counter()
        try:
            response = await client.request(method, path, json=payload)
            duration = (time.perf_counter() - started) * 1000
            query_header = response.headers.get("x-benchmark-postgres-queries")
            if query_header is None:
                raise RuntimeError("Request query-count instrumentation was missing")
            query_count = int(query_header)
            success = 200 <= response.status_code < 300
            return duration, query_count, success, str(response.status_code)
        except httpx.HTTPError:
            return (time.perf_counter() - started) * 1000, 0, False, "transport_error"

    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(index: int) -> tuple[float, int, bool, str]:
        async with semaphore:
            return await request(index)

    for index in range(warmup):
        _, _, success, status = await bounded(index)
        if not success:
            raise RuntimeError(
                f"Warm-up request failed for scenario {scenario} (HTTP {status})"
            )
    outcomes = await asyncio.gather(
        *(bounded(warmup + index) for index in range(requests))
    )
    latencies = [value[0] for value in outcomes]
    query_count = sum(value[1] for value in outcomes)
    success_count = sum(value[2] for value in outcomes)
    status_counts: dict[str, int] = {}
    for outcome in outcomes:
        status_counts[outcome[3]] = status_counts.get(outcome[3], 0) + 1
    return {
        "scenario": scenario,
        "cache_state": "not_applicable",
        "concurrency": concurrency,
        "warmup_request_count": warmup,
        "request_count": requests,
        "successful_request_count": success_count,
        "error_count": requests - success_count,
        "error_rate": (requests - success_count) / requests,
        "http_status_counts": status_counts,
        "latency_ms": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
        },
        "postgres_query_count": query_count,
        "queries_per_request": query_count / requests,
        "cache_hit_ratio": None,
        "cache_hit_ratio_label": "N/A (uncached PostgreSQL baseline)",
    }


def environment_metadata(
    database: TestDatabase, args: argparse.Namespace
) -> dict[str, Any]:
    with psycopg.connect(database.sync_url) as connection:
        version_row = connection.execute("SHOW server_version").fetchone()
    if version_row is None:
        raise RuntimeError("PostgreSQL did not return its server version")
    postgres_version = version_row[0]
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    git_dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    cpu_count = os.cpu_count()
    memory_bytes = None
    try:
        import psutil

        memory_bytes = psutil.virtual_memory().available
    except ImportError:
        if platform.system() == "Windows":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong),
                    ("avail_phys", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong),
                    ("avail_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_extended", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                memory_bytes = status.avail_phys
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_sha,
        "git_worktree_dirty": git_dirty,
        "benchmark_script_version": SCRIPT_VERSION,
        "benchmark_script_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "benchmark_configuration": {
            "scenarios": args.scenarios,
            "concurrency_levels": args.concurrency,
            "measured_requests_per_scenario_level_repetition": args.requests,
            "warmup_requests_per_scenario_level_repetition": args.warmup,
            "repetitions": args.repetitions,
            "percentile_method": "nearest-rank",
        },
        "runtime": {
            "application_environment": "development",
            "database_pool": "SQLAlchemy default pool for the long-lived API process",
            "auth_access_lifetime_seconds": 600,
            "auth_refresh_strategy": "POST /auth/refresh between batches at 80% of access lifetime",
            "python": platform.python_version(),
            "sqlalchemy": __import__("sqlalchemy").__version__,
            "fastapi": __import__("fastapi").__version__,
            "httpx": httpx.__version__,
            "uvicorn": uvicorn.__version__,
            "postgresql": postgres_version,
        },
        "host": {
            "os": platform.platform(),
            "processor": platform.processor() or None,
            "logical_cpu_count": cpu_count,
            "available_memory_bytes": memory_bytes,
        },
        "dataset": {
            "organizations": 1,
            "restaurants": 1,
            "memberships": {"owner": 1, "manager": 1, "branch_assignments": 1},
            "menus": 4,
            "items_per_menu": 40,
            "menu_items": 160,
            "inventory_ingredients": 4,
            "inventory_tracked_items": 40,
            "tracked_item_fraction": 0.25,
            "recipe_components": 40,
            "stock_per_ingredient": "5000.000 g",
            "seed_definition": "fixed catalog, recipe and stock values; one Owner and one assigned Manager; generated auth credentials remain runtime-only",
        },
        "workloads": {
            "menu-list": "100% GET /restaurants/{restaurant_id}/menus",
            "menu-items": "100% GET /menus/{menu_id}/items; menus round-robin",
            "mixed-read": "20% menu-list + 80% menu-items",
            "mixed-write": "20% catalog PUT updates (10% item, 10% menu) + 80% menu-item GETs",
            "writes_are_enabled": True,
        },
        "measurement": {
            "latency": "client-side HTTP request duration, including auth middleware, authorization and response serialization",
            "postgres_queries": "SQLAlchemy before_cursor_execute events scoped by request-local context and returned in X-Benchmark-Postgres-Queries; setup/migration/seed/login are excluded",
            "cache_hit_ratio": "N/A for this uncached baseline",
            "api_log_level": "WARNING",
        },
    }


def run_alembic(env: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        check=True,
    )


def run_benchmark(database: TestDatabase, args: argparse.Namespace) -> dict[str, Any]:
    base_env = dict(os.environ)
    for key in tuple(base_env):
        if key.startswith(("DATABASE", "TEST_DATABASE", "AUTH_", "REDIS_")) or key in {
            "ENVIRONMENT",
            "LOG_LEVEL",
        }:
            base_env.pop(key)
    env = database.environment(base=base_env)
    # A persistent API server uses the normal pool; test mode deliberately uses
    # NullPool to isolate TestClient's independent event loops.
    env["ENVIRONMENT"] = "development"
    env["LOG_LEVEL"] = "WARNING"
    run_alembic(env)
    seeded = seed_data(database)
    if args.inject_failure_after == "seed":
        raise RuntimeError("Intentional failure injected after deterministic seed")

    # Ensure application settings and its global SQLAlchemy engine can only see
    # the allocated database, even when the caller has a developer DATABASE_URL.
    os.environ.update(env)
    sys.path.insert(0, str(BACKEND))
    from app.db.database import engine
    from app.main import app

    app.add_middleware(QueryCountMiddleware)
    event.listen(engine.sync_engine, "before_cursor_execute", count_statement)
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error", access_log=False
    )
    server = uvicorn.Server(config)

    async def serve_api() -> None:
        try:
            await server.serve()
        finally:
            # Async connections must be disposed on the event loop that used them.
            await engine.dispose()

    thread = threading.Thread(target=lambda: asyncio.run(serve_api()), daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"

    async def execute() -> list[dict[str, Any]]:
        await wait_for_server(base_url, server)
        limits = httpx.Limits(
            max_connections=max(args.concurrency),
            max_keepalive_connections=max(args.concurrency),
        )
        async with httpx.AsyncClient(
            base_url=base_url,
            limits=limits,
            timeout=30,
            headers={
                "Origin": "http://localhost:3000",
                "X-CSRF-Protection": "1",
            },
        ) as client:
            response = await client.post(
                "/auth/login",
                json={"email": seeded["email"], "password": seeded["password"]},
            )
            if response.status_code != 200:
                raise RuntimeError("Benchmark Manager login failed")
            last_auth_refresh = time.perf_counter()
            results = []
            for repetition in range(args.repetitions):
                for scenario in args.scenarios:
                    for concurrency in args.concurrency:
                        if time.perf_counter() - last_auth_refresh >= 480:
                            refresh = await client.post("/auth/refresh")
                            if refresh.status_code != 200:
                                raise RuntimeError("Benchmark session refresh failed")
                            last_auth_refresh = time.perf_counter()
                        result = await measure_scenario(
                            client,
                            scenario=scenario,
                            requests=args.requests,
                            warmup=args.warmup,
                            concurrency=concurrency,
                            menu_ids=seeded["menu_ids"],
                            item_ids=seeded["menu_item_ids"],
                            restaurant_id=seeded["restaurant_id"],
                        )
                        result["repetition"] = repetition + 1
                        results.append(result)
                        print(
                            f"{scenario:12} c={concurrency:>2} rep={repetition + 1}: "
                            f"n={args.requests} p50={result['latency_ms']['p50']:.2f}ms "
                            f"p95={result['latency_ms']['p95']:.2f}ms "
                            f"p99={result['latency_ms']['p99']:.2f}ms "
                            f"queries/request={result['queries_per_request']:.2f} "
                            f"errors={result['error_count']}",
                            flush=True,
                        )
                        if args.inject_failure_after == "measurement" and results:
                            raise RuntimeError(
                                "Intentional failure injected after measurement"
                            )
            return results

    try:
        results = asyncio.run(execute())
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=5)
        event.remove(engine.sync_engine, "before_cursor_execute", count_statement)
        if thread.is_alive():
            raise RuntimeError("API server process thread did not terminate")
    return {
        "schema_version": 1,
        "benchmark": "restaurantos-menu-read-baseline",
        "cache_mode": "disabled",
        "metadata": environment_metadata(database, args),
        "results": results,
    }


def write_artifact(result: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"menu-read-baseline-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.json"
    destination = output_dir / name
    temporary = destination.with_suffix(".json.tmp")
    try:
        temporary.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requests",
        type=int,
        default=1000,
        help="measured requests per scenario/concurrency/repetition",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=50,
        help="excluded warm-up requests per scenario/concurrency/repetition",
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--concurrency", type=parse_int_list, default=DEFAULT_CONCURRENCY
    )
    parser.add_argument(
        "--scenarios", type=lambda value: tuple(value.split(",")), default=SCENARIOS
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--inject-failure-after",
        choices=("seed", "measurement"),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if min(args.requests, args.repetitions) < 1 or args.warmup < 0:
        parser.error(
            "requests and repetitions must be positive; warmup cannot be negative"
        )
    if not args.scenarios or any(name not in SCENARIOS for name in args.scenarios):
        parser.error(f"scenarios must be chosen from: {', '.join(SCENARIOS)}")
    artifact: Path | None = None
    try:
        with disposable_database(prefix="restaurantos_benchmark") as database:
            result = run_benchmark(database, args)
            artifact = write_artifact(result, args.output_dir)
    except Exception as error:  # noqa: BLE001 - guarantee cleanup and a nonzero runner exit
        if artifact is not None:
            artifact.unlink(missing_ok=True)
        print(f"Benchmark failed: {type(error).__name__}", file=sys.stderr)
        traceback.print_tb(error.__traceback__, limit=20, file=sys.stderr)
        return 1
    print(f"\nResults written to {artifact}")
    print(f"Commit: {result['metadata']['git_commit']}")
    print(f"Runs: {len(result['results'])}; cache hit ratio: N/A (uncached baseline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
