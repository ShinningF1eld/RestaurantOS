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
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import psycopg
import uvicorn
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_support.disposable_postgres import TestDatabase, disposable_database

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPT_VERSION = "2.3.0"
DEFAULT_OUTPUT = ROOT / "artifacts" / "benchmarks"
SCENARIOS = ("menu-list", "menu-items", "mixed-read", "mixed-write")
DEFAULT_CONCURRENCY = (1, 10, 25, 50)
QUERY_COUNT: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar(
    "benchmark_query_count", default=None
)
DETAILS: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "benchmark_details", default=None
)
PHASE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "benchmark_phase", default="other"
)
PHASES = (
    "authentication",
    "authorization",
    "live_stock",
    "catalog_source",
    "analytics",
    "other",
)


@contextmanager
def socket_poll_guard():
    """Treat Windows' concurrently closed pooled socket as expired, not retryable."""
    count = [0]
    if sys.platform != "win32":
        yield count
        return
    import httpcore._backends.anyio as backend

    original = backend.is_socket_readable

    def readable(sock):
        try:
            return original(sock)
        except OSError as error:
            if getattr(error, "winerror", None) != 10038:
                raise
            # HTTPcore already treats missing/negative descriptors as readable
            # (expired). Windows select can instead raise after its fd check.
            count[0] += 1
            return True

    with patch.object(backend, "is_socket_readable", readable):
        yield count


def install_instrumentation(stack: ExitStack, cache_state: str) -> None:
    """Process-local observers; never replace authorization or live-stock reads."""
    from unittest.mock import patch

    from app.modules.analytics.repo.queries import AnalyticsRepository
    from app.modules.catalog.menu_cache import CatalogMenuCache, MenuListLookup
    from app.modules.catalog.repo.queries import CatalogRepository
    from app.modules.recipes.service import RecipeAvailabilityService
    from app.modules.tenancy.access import AccessService

    def phase_wrapper(original: Any, phase: str) -> Any:
        @wraps(original)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            token = PHASE.set(phase)
            if phase == "catalog_source" and DETAILS.get() is not None:
                DETAILS.get()["hit"] = False
            try:
                return await original(*args, **kwargs)
            finally:
                PHASE.reset(token)

        return wrapped

    for cls, names, phase in (
        (AccessService, ("current", "restaurant"), "authorization"),
        (CatalogRepository, ("get_menu_by_id",), "authorization"),
        (
            CatalogRepository,
            ("list_menus_for_restaurant", "list_menu_items_for_menu"),
            "catalog_source",
        ),
        (RecipeAvailabilityService, ("for_menu_items",), "live_stock"),
        (
            AnalyticsRepository,
            ("get_completed_totals", "get_sales_graph", "get_top_selling_items"),
            "analytics",
        ),
    ):
        for name in names:
            stack.enter_context(
                patch.object(cls, name, phase_wrapper(getattr(cls, name), phase))
            )

    def lookup_wrapper(original: Any, items: bool) -> Any:
        @wraps(original)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            if cache_state == "disabled":
                result = (
                    (None, False)
                    if items
                    else MenuListLookup(menus=None, redis_available=False)
                )
            else:
                result = await original(*args, **kwargs)
            details = DETAILS.get()
            if details is not None:
                details["hit"] = (
                    (result[0] is not None) if items else (result.menus is not None)
                )
            return result

        return wrapped

    for name, items in (("lookup", False), ("lookup_menu_items", True)):
        stack.enter_context(
            patch.object(
                CatalogMenuCache,
                name,
                lookup_wrapper(getattr(CatalogMenuCache, name), items),
            )
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
        detail_token = DETAILS.set(
            {
                "hit": None,
                "counts": dict.fromkeys(PHASES, 0),
                "sql_ms": dict.fromkeys(PHASES, 0.0),
            }
        )

        async def add_count_header(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-benchmark-postgres-queries", str(counter[0]).encode())
                )
                headers.append(
                    (b"x-benchmark-details", json.dumps(DETAILS.get()).encode())
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, add_count_header)
        finally:
            QUERY_COUNT.reset(token)
            DETAILS.reset(detail_token)


def count_statement(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    counter = QUERY_COUNT.get()
    if counter is not None:
        counter[0] += 1
    details = DETAILS.get()
    if details is not None:
        phase = PHASE.get()
        if phase == "other" and any(
            table in statement
            for table in ("auth_sessions", "users", "auth_refresh_tokens")
        ):
            phase = "authentication"
        details["counts"][phase] += 1
        context.benchmark_phase = phase
        context.benchmark_started = time.perf_counter()


def time_statement(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    details = DETAILS.get()
    if details is not None:
        details["sql_ms"][context.benchmark_phase] += (
            time.perf_counter() - context.benchmark_started
        ) * 1000


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
                "organization_id": str(organization.id),
                "restaurant_id": restaurant.id,
                "menu_ids": menu_ids,
                "menu_item_ids": item_ids,
                "email": manager.email,
                "password": password,
            }
        finally:
            await engine.dispose()

    return asyncio.run(seed())


async def wait_for_server(url: str, server: subprocess.Popen[str]) -> None:
    async with httpx.AsyncClient() as client:
        for _ in range(150):
            if server.poll() is not None:
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
    if scenario == "dashboard":
        return "GET", f"/api/restaurants/{restaurant_id}/analytics/dashboard", None
    menu_id = menu_ids[index % len(menu_ids)]
    if scenario == "menu-items":
        return "GET", f"/menus/{menu_id}/items", None
    if scenario == "mixed-read":
        if index % 5 == 0:
            return "GET", f"/restaurants/{restaurant_id}/menus", None
        return "GET", f"/menus/{menu_id}/items", None
    if scenario == "mixed-write" and index % 10 == 0:
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
    if scenario == "mixed-write" and index % 10 == 1:
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
    inject_request_failure: bool = False,
    cache_state: str = "disabled",
    before_measurement: Any = None,
) -> dict[str, Any]:
    async def request(index: int) -> tuple[float, int, bool, str, dict[str, Any]]:
        method, path, payload = request_plan(
            scenario, index, menu_ids, item_ids, restaurant_id
        )
        if inject_request_failure and index == warmup:
            method, path, payload = "GET", "/menus/0/items", None
        started = time.perf_counter()
        try:
            response = await client.request(method, path, json=payload)
            duration = (time.perf_counter() - started) * 1000
            query_header = response.headers.get("x-benchmark-postgres-queries")
            if query_header is None:
                raise RuntimeError("Request query-count instrumentation was missing")
            query_count = int(query_header)
            success = 200 <= response.status_code < 300
            detail_header = response.headers.get("x-benchmark-details")
            if detail_header is None:
                raise RuntimeError("Request cache/phase instrumentation was missing")
            details = json.loads(detail_header)
            if sum(details["counts"].values()) != query_count:
                raise RuntimeError("SQL phase totals do not match query count")
            return duration, query_count, success, str(response.status_code), details
        except httpx.HTTPError as error:
            return (
                (time.perf_counter() - started) * 1000,
                0,
                False,
                f"transport_error:{type(error).__name__}",
                {},
            )

    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(index: int) -> tuple[float, int, bool, str, dict[str, Any]]:
        async with semaphore:
            return await request(index)

    for index in range(warmup):
        _, _, success, status, _ = await bounded(index)
        if not success:
            raise RuntimeError(
                f"Warm-up request failed for scenario {scenario} (HTTP {status})"
            )
    if before_measurement is not None:
        await before_measurement()
    outcomes = await asyncio.gather(
        *(bounded(warmup + index) for index in range(requests))
    )
    latencies = [value[0] for value in outcomes]
    query_count = sum(value[1] for value in outcomes)
    success_count = sum(value[2] for value in outcomes)
    status_counts: dict[str, int] = {}
    for outcome in outcomes:
        status_counts[outcome[3]] = status_counts.get(outcome[3], 0) + 1
    if success_count != requests:
        print(
            f"Measured failure: scenario={scenario}; concurrency={concurrency}; unsuccessful={requests - success_count}; statuses={status_counts}",
            file=sys.stderr,
            flush=True,
        )
        if inject_request_failure:
            raise RuntimeError("Intentional measured request failure")
    observed = [value for value in outcomes if value[4]]
    if not observed:
        raise RuntimeError("No responses with observable SQL/cache measurements")
    # Lost responses have unknown server SQL/cache work, not zero queries.
    # Preserve all request latencies/errors but normalize SQL over observed responses.
    lookups = [value[4]["hit"] for value in observed if value[4]["hit"] is not None]
    hits = sum(lookups)
    return {
        "scenario": scenario,
        "cache_state": cache_state,
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
        "sql_observed_response_count": len(observed),
        "sql_unknown_request_count": requests - len(observed),
        "queries_per_request": query_count / len(observed),
        "query_denominator": "instrumented HTTP responses; lost-response server work unknown",
        "cache_lookup_count": len(lookups),
        "cache_hit_count": hits,
        "cache_hit_ratio": hits / len(lookups)
        if lookups and cache_state != "disabled"
        else None,
        "cache_hit_ratio_label": "validated payload reused without source reload / catalog GETs"
        if cache_state != "disabled"
        else "N/A (disabled)",
        "sql_phase_costs": {
            phase: {
                "queries_per_request": sum(
                    value[4]["counts"][phase] for value in observed
                )
                / len(observed),
                "mean_execution_ms_per_request": sum(
                    value[4]["sql_ms"][phase] for value in observed
                )
                / len(observed),
            }
            for phase in PHASES
        },
        "first_wave_latency_ms": {
            "p50": percentile(latencies[:concurrency], 50),
            "p95": percentile(latencies[:concurrency], 95),
            "p99": percentile(latencies[:concurrency], 99),
        },
        "first_wave_hit_count": sum(
            value[4].get("hit") is True for value in outcomes[:concurrency]
        ),
    }


def environment_metadata(
    database: TestDatabase, args: argparse.Namespace, settings: Any
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
            "cache_state": args.cache_state,
            "scenarios": args.scenarios,
            "concurrency_levels": args.concurrency,
            "measured_requests_per_scenario_level_repetition": args.requests,
            "warmup_requests_per_scenario_level_repetition": args.warmup,
            "repetitions": args.repetitions,
            "percentile_method": "nearest-rank",
        },
        "runtime": {
            "application_environment": settings.environment,
            "database_pool": "SQLAlchemy default pool for the long-lived API process",
            "api_execution": "separate API subprocess and HTTP load-generator process; no shared Python interpreter/GIL",
            "http_request_timeout_seconds": 30,
            "uvicorn_keep_alive_seconds": 5,
            "windows_socket_poll_guard": "WinError 10038 during idle pool check means expired; no request replay",
            "expired_windows_socket_poll_count": getattr(
                args, "expired_socket_poll_count", [0]
            )[0],
            "auth_access_lifetime_seconds": settings.auth_access_seconds,
            "effective_settings": {
                key: getattr(settings, key)
                for key in (
                    "environment",
                    "log_level",
                    "database_echo",
                    "auth_cookie_secure",
                    "auth_trusted_origins",
                    "auth_access_seconds",
                    "auth_session_seconds",
                    "auth_jwt_issuer",
                    "auth_jwt_audience",
                    "auth_login_email_limit",
                    "auth_login_ip_limit",
                    "auth_login_window_seconds",
                    "auth_refresh_family_limit",
                    "auth_refresh_ip_limit",
                    "auth_refresh_window_seconds",
                )
            },
            "configuration_source": "explicit Settings defaults and benchmark overrides; dotenv and ambient settings ignored",
            "auth_refresh_strategy": "POST /auth/refresh between batches at 80% of access lifetime",
            "python": platform.python_version(),
            "sqlalchemy": __import__("sqlalchemy").__version__,
            "fastapi": __import__("fastapi").__version__,
            "httpx": httpx.__version__,
            "uvicorn": uvicorn.__version__,
            "postgresql": postgres_version,
            "redis": args.redis_version,
            "redis_operation_budget_ms": settings.redis_operation_budget_ms,
            "redis_max_connections": settings.redis_max_connections,
            "catalog_absolute_age_seconds": 10,
        },
        "host": {
            "os": platform.platform(),
            "processor": platform.processor() or None,
            "logical_cpu_count": cpu_count,
            "available_memory_bytes": memory_bytes,
        },
        "dataset": {
            "dashboard_history": "700 completed paid orders over seven days, two immutable item snapshots per order"
            if "dashboard" in args.scenarios
            else "no orders (original catalog workload)",
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
            "cache_hit_ratio": "request-local validated cache lookup, cleared if source list reloads; denominator catalog GETs only",
            "sql_phase_costs": "nonoverlapping before/after cursor execution counts and durations; includes database wait/driver time, excludes DTO/Python/HTTP time; not additive latency percentiles",
            "api_log_level": "WARNING",
        },
    }


def seed_dashboard_history(database: TestDatabase, seeded: dict[str, Any]) -> None:
    """Separate evaluation dataset; never changes the original menu workload."""
    from datetime import timedelta

    from psycopg import sql

    with psycopg.connect(database.sync_url) as connection:
        for index in range(700):
            created = datetime.now(UTC).astimezone().replace(
                tzinfo=None, hour=12, minute=0, second=0, microsecond=0
            ) - timedelta(days=index % 7)
            order_id = connection.execute(
                "INSERT INTO orders (restaurant_id, status, payment_status, subtotal, total, created_at, updated_at) VALUES (%s, 'COMPLETED', 'PAID', 24, 24, %s, %s) RETURNING order_id",
                (seeded["restaurant_id"], created, created),
            ).fetchone()[0]
            for offset in (0, 1):
                connection.execute(
                    sql.SQL(
                        "INSERT INTO order_items (order_id, menu_item_id, quantity, unit_price, item_name, line_total) VALUES (%s, %s, 1, 12, %s, 12)"
                    ),
                    (
                        order_id,
                        seeded["menu_item_ids"][(index + offset) % 160],
                        f"Historical Item {(index + offset) % 160:03d}",
                    ),
                )


def frozen_settings(values: dict[str, Any]) -> Any:
    """Validate explicit inputs without reading any ambient settings source."""
    sys.path.insert(0, str(BACKEND))
    from app.core.config import Settings

    class BenchmarkSettings(Settings):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Any,
            init_settings: Any,
            env_settings: Any,
            dotenv_settings: Any,
            file_secret_settings: Any,
        ) -> tuple[Any, ...]:
            # Skip ambient sources entirely, including their JSON parsing. Keep
            # the application's normal field and model validators unchanged.
            return (init_settings,)

    return BenchmarkSettings(_env_file=None, **values)


def isolated_settings(database: TestDatabase, redis_port: str) -> Any:
    """Supply every field explicitly so neither dotenv nor ambient env wins."""
    sys.path.insert(0, str(BACKEND))
    from app.core.config import Settings

    generated = database.environment(base={})
    values = {
        name: field.get_default(call_default_factory=True)
        for name, field in Settings.model_fields.items()
        if not field.is_required()
    }
    values.update(
        database_url=database.async_url,
        auth_jwt_secret=generated["AUTH_JWT_SECRET"],
        auth_rate_limit_secret=generated["AUTH_RATE_LIMIT_SECRET"],
        environment="development",
        log_level="WARNING",
        database_echo=False,
        auth_cookie_secure=False,
        auth_trusted_origins=["http://localhost:3000"],
        redis_url=f"redis://127.0.0.1:{redis_port}/0",
    )
    return frozen_settings(values)


def serve_api_worker() -> int:
    """Private subprocess bootstrap; settings/secrets stay in runtime IPC only."""
    configuration = json.loads(os.environ.pop("_RESTAURANTOS_BENCHMARK_CONFIG"))
    settings = frozen_settings(configuration["settings"])
    import app.core.config as application_config

    application_config.get_settings = lambda: settings
    from app.db.database import engine
    from app.main import app

    with ExitStack() as stack:
        install_instrumentation(stack, configuration["cache_state"])
        if configuration.get("dashboard"):
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "dashboard_extension", ROOT / "scripts/benchmark-dashboard-cache.py"
            )
            extension = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(extension)
            extension.install_dashboard_queries(
                stack, sys.modules[__name__], configuration["dashboard"] == "prototype"
            )
        app.add_middleware(QueryCountMiddleware)
        event.listen(engine.sync_engine, "before_cursor_execute", count_statement)
        event.listen(engine.sync_engine, "after_cursor_execute", time_statement)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=configuration["port"],
                log_level="error",
                access_log=False,
            )
        )

        def stop_on_input() -> None:
            sys.stdin.readline()
            server.should_exit = True

        threading.Thread(target=stop_on_input, daemon=True).start()

        async def serve() -> None:
            try:
                await server.serve()
            finally:
                await engine.dispose()

        asyncio.run(serve())
    return 0


def run_alembic() -> None:
    from alembic import command
    from alembic.config import Config

    # Alembic and the application resolve the same frozen settings instance.
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")


def run_benchmark(database: TestDatabase, args: argparse.Namespace) -> dict[str, Any]:
    settings = isolated_settings(database, args.redis_port)
    import app.core.config as application_config

    # Install before migrations, seed imports or engine construction. This is
    # confined to the dedicated benchmark process; production code is unchanged.
    application_config.get_settings = lambda: settings
    run_alembic()
    seeded = seed_data(database)
    if "dashboard" in args.scenarios:
        seed_dashboard_history(database, seeded)
    if args.inject_failure_after == "seed":
        raise RuntimeError("Intentional failure injected after deterministic seed")

    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    explicit = settings.model_dump(mode="json")
    for name in ("auth_jwt_secret", "auth_rate_limit_secret", "redis_url"):
        explicit[name] = getattr(settings, name).get_secret_value()
    environment = {
        **os.environ,
        "_RESTAURANTOS_BENCHMARK_CONFIG": json.dumps(
            {
                "settings": explicit,
                "port": port,
                "cache_state": args.cache_state,
                "dashboard": getattr(args, "dashboard_mode", None),
            }
        ),
    }
    server = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--serve"],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    base_url = f"http://127.0.0.1:{port}"

    async def execute() -> list[dict[str, Any]]:
        from redis.asyncio import Redis
        from redis.exceptions import RedisError
        from tests.support.owned_redis import docker

        await wait_for_server(base_url, server)
        redis_control = Redis(
            host="127.0.0.1", port=int(args.redis_port), socket_timeout=2
        )
        prefix = f"restaurantos:development:catalog:v1:org:{seeded['organization_id']}:"
        keys = [
            f"{prefix}restaurant:{seeded['restaurant_id']}:menus",
            *[f"{prefix}menu:{menu_id}:items" for menu_id in seeded["menu_ids"]],
        ]

        async def clear_catalog() -> None:
            await redis_control.delete(*keys)

        async def restart_redis() -> None:
            await asyncio.to_thread(docker, "stop", args.redis_container)
            trigger = await client.get(f"/menus/{seeded['menu_ids'][0]}/items")
            if trigger.status_code != 200:
                raise RuntimeError("Excluded outage-trigger request failed")
            await asyncio.to_thread(docker, "start", args.redis_container)
            for _ in range(50):
                try:
                    if await redis_control.ping():
                        break
                except RedisError:
                    await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Owned Redis restart failed")
            # No clock overrides: allow the production five-second circuit probe.
            await asyncio.sleep(5.1)
            await clear_catalog()

        limits = httpx.Limits(
            max_connections=max(args.concurrency),
            max_keepalive_connections=max(args.concurrency),
        )
        async with (
            redis_control,
            httpx.AsyncClient(
                base_url=base_url,
                limits=limits,
                timeout=30,
                headers={
                    "Origin": "http://localhost:3000",
                    "X-CSRF-Protection": "1",
                },
            ) as client,
        ):
            response = await client.post(
                "/auth/login",
                json={"email": seeded["email"], "password": seeded["password"]},
            )
            if response.status_code != 200:
                raise RuntimeError("Benchmark Manager login failed")
            last_auth_refresh = time.perf_counter()
            results = []
            outage_started = False
            for repetition in range(args.repetitions):
                for scenario in args.scenarios:
                    for concurrency in args.concurrency:
                        if not outage_started:
                            await clear_catalog()
                        before_measurement = None
                        if args.cache_state == "cold":
                            before_measurement = clear_catalog
                        elif args.cache_state == "restart":
                            before_measurement = restart_redis
                        elif args.cache_state == "outage" and not outage_started:

                            async def stop_redis() -> None:
                                await asyncio.to_thread(
                                    docker, "stop", args.redis_container
                                )

                            before_measurement = stop_redis
                            outage_started = True
                        if (
                            time.perf_counter() - last_auth_refresh
                            >= settings.auth_access_seconds * 0.8
                        ):
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
                            inject_request_failure=args.inject_failure_after
                            == "request",
                            cache_state=args.cache_state,
                            before_measurement=before_measurement,
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
        try:
            server.communicate(input="stop\n", timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
            raise RuntimeError("Benchmark API required forced termination") from None
        if server.returncode != 0:
            raise RuntimeError("Benchmark API subprocess exited unsuccessfully")
    return {
        "schema_version": 2,
        "benchmark": "restaurantos-menu-read-comparison",
        "cache_mode": args.cache_state,
        "metadata": environment_metadata(database, args, settings),
        "results": results,
    }


def write_artifact(result: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"menu-read-{result['cache_mode']}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.json"
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
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--cache-state",
        choices=("disabled", "cold", "warm", "outage", "restart"),
        default="disabled",
    )
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="allocate disposable Compose PostgreSQL without TEST_DATABASE_URL",
    )
    parser.add_argument(
        "--inject-failure-after",
        choices=("seed", "measurement", "request"),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.serve:
        return serve_api_worker()
    if min(args.requests, args.repetitions) < 1 or args.warmup < 0:
        parser.error(
            "requests and repetitions must be positive; warmup cannot be negative"
        )
    if not args.scenarios or any(
        name not in (*SCENARIOS, "dashboard") for name in args.scenarios
    ):
        parser.error(f"scenarios must be chosen from: {', '.join(SCENARIOS)}")
    artifact: Path | None = None
    try:
        sys.path.insert(0, str(BACKEND))
        from tests.support.owned_redis import docker, owned_redis

        with ExitStack() as stack:
            args.expired_socket_poll_count = stack.enter_context(socket_poll_guard())
            if args.isolated:
                from validate import services

                environment = stack.enter_context(services(False))
            else:
                environment = os.environ
            args.redis_container, args.redis_port = stack.enter_context(owned_redis())
            args.redis_version = docker(
                "exec", args.redis_container, "redis-server", "--version"
            )
            database = stack.enter_context(
                disposable_database(
                    prefix="restaurantos_benchmark",
                    test_url=environment.get("TEST_DATABASE_URL"),
                )
            )
            result = run_benchmark(database, args)
        # Publish only after API, database, Redis and Compose cleanup succeed.
        artifact = write_artifact(result, args.output_dir)
    except Exception as error:  # noqa: BLE001 - guarantee cleanup and a nonzero runner exit
        if artifact is not None:
            artifact.unlink(missing_ok=True)
        print(f"Benchmark failed: {type(error).__name__}", file=sys.stderr)
        if isinstance(error, OSError):
            print(
                f"OS error codes: errno={error.errno}; winerror={getattr(error, 'winerror', None)}",
                file=sys.stderr,
            )
        traceback.print_tb(error.__traceback__, limit=20, file=sys.stderr)
        return 1
    print(f"\nResults written to {artifact}")
    print(f"Commit: {result['metadata']['git_commit']}")
    print(f"Runs: {len(result['results'])}; cache mode: {result['cache_mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
