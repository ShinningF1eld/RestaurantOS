"""Benchmark regressions without database, application engine or network."""

import asyncio
from collections import Counter
from contextlib import contextmanager
import importlib.util
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
    settings = benchmark.isolated_settings(database)
    assert settings.database_url == database.async_url
    assert settings.auth_access_seconds == 600
    assert settings.auth_refresh_window_seconds == 60
    assert settings.database_echo is False
    assert settings.environment == "development"
    assert settings.auth_jwt_secret != settings.auth_rate_limit_secret


@pytest.mark.parametrize("failure", ["http", "transport", "instrumentation"])
def test_measured_failures_reject_baseline_without_warmup(benchmark, failure):
    def handler(request):
        if failure == "transport":
            raise httpx.ConnectError("unavailable", request=request)
        if failure == "instrumentation":
            return httpx.Response(200)
        return httpx.Response(500, headers={"x-benchmark-postgres-queries": "3"})

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


def test_successful_metrics_exclude_warmup_queries(benchmark):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"x-benchmark-postgres-queries": "6"})

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
    cleaned = []

    @contextmanager
    def owned_database(**kwargs):
        try:
            yield object()
        finally:
            cleaned.append(True)

    def fail(database, args):
        raise RuntimeError("Measured workload failed")

    monkeypatch.setattr(benchmark, "disposable_database", owned_database)
    monkeypatch.setattr(benchmark, "run_benchmark", fail)
    monkeypatch.setattr(sys, "argv", ["benchmark", "--output-dir", str(tmp_path)])
    assert benchmark.main() == 1
    assert cleaned == [True]
    assert list(tmp_path.iterdir()) == []


def test_atomic_artifact_failure_removes_temporary_file(
    benchmark, monkeypatch, tmp_path
):
    def fail_replace(*args):
        raise OSError("write interrupted")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        benchmark.write_artifact({"results": []}, tmp_path)
    assert list(tmp_path.iterdir()) == []
