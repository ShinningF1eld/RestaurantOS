"""Benchmark regressions without database, application engine or network."""

import asyncio
from collections import Counter
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest


@pytest.fixture
def benchmark(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "menu_read_benchmark", root / "scripts/benchmark-menu-reads.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("code", [10038, 10054])
def test_windows_pool_guard_expires_only_closed_socket(benchmark, monkeypatch, code):
    import httpcore._backends.anyio as backend

    error = OSError("safe test failure")
    error.winerror = code

    def original(sock):
        raise error

    monkeypatch.setattr(backend, "is_socket_readable", original)
    monkeypatch.setattr(benchmark.sys, "platform", "win32")
    with benchmark.socket_poll_guard() as count:
        if code == 10038:
            assert backend.is_socket_readable(None) is True
            assert count == [1]
        else:
            with pytest.raises(OSError):
                backend.is_socket_readable(None)
            assert count == [0]
    assert backend.is_socket_readable is original


@pytest.mark.parametrize("start", [0, 2, 50, 103])
def test_mixed_write_ratio_is_twenty_percent_at_any_warmup_offset(benchmark, start):
    plans = [
        benchmark.request_plan("mixed-write", i, [1, 2, 3, 4], list(range(1, 161)), 1)
        for i in range(start, start + 1000)
    ]
    counts = Counter(
        "item-write"
        if method == "PUT" and path.startswith("/menu-items/")
        else "menu-write"
        if method == "PUT"
        else "read"
        for method, path, _ in plans
    )
    assert counts == {"item-write": 100, "menu-write": 100, "read": 800}


def test_configuration_ignores_environment_and_dotenv(benchmark, monkeypatch, tmp_path):
    from app.core.config import Settings
    from test_support.disposable_postgres import TestDatabase

    dotenv = tmp_path / ".env"
    dotenv.write_text("AUTH_ACCESS_SECONDS=8\nDATABASE_ECHO=true\n")
    monkeypatch.setitem(Settings.model_config, "env_file", dotenv)
    monkeypatch.setenv("AUTH_ACCESS_SECONDS", "7")
    monkeypatch.setenv("AUTH_REFRESH_WINDOW_SECONDS", "1")
    monkeypatch.setenv("DATABASE_ECHO", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_TRUSTED_ORIGINS", "invalid-json")
    monkeypatch.setenv("AUTH_TRUSTED_PROXY_IPS", "invalid-json")
    database = TestDatabase(
        "owned_test",
        "postgresql+asyncpg://localhost/owned_test",
        "postgresql://localhost/owned_test",
    )
    monkeypatch.setenv("REDIS_URL", "redis://developer.invalid:6379/0")
    settings = benchmark.isolated_settings(database, "12345")
    assert settings.database_url == database.async_url
    assert settings.auth_access_seconds == 600
    assert settings.auth_refresh_window_seconds == 60
    assert settings.database_echo is False
    assert settings.environment == "development"
    assert settings.auth_jwt_secret != settings.auth_rate_limit_secret
    assert settings.redis_url.get_secret_value() == "redis://127.0.0.1:12345/0"


def metric_headers(benchmark, queries, *, hit=False):
    counts = dict.fromkeys(benchmark.PHASES, 0)
    counts["authorization"] = queries
    return {
        "x-benchmark-postgres-queries": str(queries),
        "x-benchmark-details": json.dumps(
            {
                "hit": hit,
                "counts": counts,
                "sql_ms": dict.fromkeys(benchmark.PHASES, 0.0),
            }
        ),
    }


@pytest.mark.parametrize("failure", ["transport", "instrumentation"])
def test_measured_failures_reject_baseline_without_warmup(benchmark, failure):
    def handler(request):
        if failure == "transport":
            raise httpx.ConnectError("unavailable", request=request)
        if failure == "instrumentation":
            return httpx.Response(200)
        return httpx.Response(500, headers=metric_headers(benchmark, 3))

    async def execute():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        ) as client:
            await benchmark.measure_scenario(
                client,
                scenario="menu-list",
                requests=5,
                warmup=0,
                concurrency=2,
                menu_ids=[1],
                item_ids=[1],
                restaurant_id=1,
            )

    with pytest.raises(RuntimeError):
        asyncio.run(execute())


@pytest.mark.parametrize("failure", ["http", "transport"])
def test_complete_measurement_retains_errors_and_unknown_sql(benchmark, failure):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure == "transport":
                raise httpx.ReadError("lost", request=request)
            return httpx.Response(500, headers=metric_headers(benchmark, 3))
        return httpx.Response(200, headers=metric_headers(benchmark, 3, hit=True))

    async def execute():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        ) as client:
            return await benchmark.measure_scenario(
                client,
                scenario="menu-list",
                requests=5,
                warmup=0,
                concurrency=2,
                menu_ids=[1],
                item_ids=[1],
                restaurant_id=1,
                cache_state="warm",
            )

    result = asyncio.run(execute())
    assert result["error_count"] == 1
    assert result["error_rate"] == 0.2
    assert result["successful_request_count"] == 4
    assert result["sql_unknown_request_count"] == (failure == "transport")
    assert result["sql_observed_response_count"] == (4 if failure == "transport" else 5)
    assert result["queries_per_request"] == 3
    assert result["cache_hit_count"] == 4
    assert sum(result["http_status_counts"].values()) == 5


def test_successful_metrics_exclude_warmup_queries(benchmark):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers=metric_headers(benchmark, 6, hit=True))

    async def execute():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        ) as client:
            return await benchmark.measure_scenario(
                client,
                scenario="menu-list",
                requests=20,
                warmup=3,
                concurrency=2,
                menu_ids=[1],
                item_ids=[1],
                restaurant_id=1,
            )

    result = asyncio.run(execute())
    assert calls == 23
    assert result["postgres_query_count"] == 120
    assert result["request_count"] == result["successful_request_count"] == 20
    assert result["error_count"] == 0
    assert set(result["latency_ms"]) == {"p50", "p95", "p99"}


def test_main_failure_exits_nonzero_and_cleans_without_artifact(
    benchmark, monkeypatch, tmp_path
):
    from tests.support import owned_redis as redis_support

    cleaned = []

    @contextmanager
    def redis():
        try:
            yield "owned", "12345"
        finally:
            cleaned.append("redis")

    @contextmanager
    def owned_database(**kwargs):
        try:
            yield object()
        finally:
            cleaned.append(True)

    def fail(database, args):
        raise RuntimeError("Measured workload failed")

    monkeypatch.setattr(benchmark, "disposable_database", owned_database)
    monkeypatch.setattr(redis_support, "owned_redis", redis)
    monkeypatch.setattr(redis_support, "docker", lambda *args: "Redis version")
    monkeypatch.setattr(benchmark, "install_instrumentation", lambda *args: None)
    monkeypatch.setattr(benchmark, "run_benchmark", fail)
    monkeypatch.setattr(sys, "argv", ["benchmark", "--output-dir", str(tmp_path)])
    assert benchmark.main() == 1
    assert cleaned == [True, "redis"]
    assert list(tmp_path.iterdir()) == []


def test_atomic_artifact_failure_removes_temporary_file(
    benchmark, monkeypatch, tmp_path
):
    def fail_replace(*args):
        raise OSError("write interrupted")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        benchmark.write_artifact({"results": [], "cache_mode": "disabled"}, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cold_reset_runs_after_warmup_and_write_requests_do_not_dilute_hits(benchmark):
    reset = False
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        hit = None if request.method == "PUT" else reset
        return httpx.Response(200, headers=metric_headers(benchmark, 6, hit=hit))

    async def clear():
        nonlocal reset
        assert calls == 50
        reset = True

    async def execute():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        ) as client:
            return await benchmark.measure_scenario(
                client,
                scenario="mixed-write",
                requests=1000,
                warmup=50,
                concurrency=10,
                menu_ids=[1, 2, 3, 4],
                item_ids=list(range(1, 161)),
                restaurant_id=1,
                cache_state="cold",
                before_measurement=clear,
            )

    result = asyncio.run(execute())
    assert result["cache_lookup_count"] == result["cache_hit_count"] == 800
    assert result["cache_hit_ratio"] == 1
    assert result["first_wave_hit_count"] == 8
    assert result["sql_phase_costs"]["authorization"]["queries_per_request"] == 6
