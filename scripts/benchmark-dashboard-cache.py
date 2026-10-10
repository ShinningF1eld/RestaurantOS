"""Benchmark-only dashboard cache experiment; no production cache is installed."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any
from unittest.mock import patch

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1]


def install_prototype(stack: Any, benchmark: Any) -> None:
    from app.modules.analytics.repo.queries import (
        AnalyticsRepository,
        CompletedTotals,
        SalesGraphRow,
        TopSellingItemRow,
    )
    from app.redis.adapter import RedisFailure

    def wrap(original: Any, row_type: Any, many: bool) -> Any:
        @wraps(original)
        async def cached(
            self: Any, restaurant_id: int, *args: Any, **kwargs: Any
        ) -> Any:
            from app.main import app

            # Service always resolves live membership, assignment, capability and
            # restaurant scope before calling these repository methods.
            redis = app.state.redis
            fingerprint = hashlib.sha256(
                repr((args, sorted(kwargs.items()))).encode()
            ).hexdigest()
            key = f"{redis.namespace('benchmark-dashboard', 1)}org:{self._scope.organization_id}:restaurant:{restaurant_id}:{original.__name__}:{fingerprint}"
            details = benchmark.DETAILS.get()
            try:
                raw = await redis.execute("GET", key)
                if raw is not None:
                    payload = json.loads(raw)
                    if 0 <= time.time() - payload["started"] < 10:
                        rows = payload["rows"]
                        for row in rows:
                            row["sales"] = Decimal(row["sales"])
                        if details is not None and details["hit"] is None:
                            details["hit"] = True
                        objects = [row_type(**row) for row in rows]
                        return objects if many else objects[0]
            except RedisFailure:
                pass
            if details is not None:
                details["hit"] = False
            started = time.time()
            result = await original(self, restaurant_id, *args, **kwargs)
            remaining = 10000 - int((time.time() - started) * 1000)
            if remaining > 0:
                rows = result if many else [result]
                payload = json.dumps(
                    {"started": started, "rows": [asdict(row) for row in rows]},
                    default=str,
                )
                try:
                    await redis.execute("SET", key, payload, "PX", remaining)
                except RedisFailure:
                    pass
            return result

        return cached

    for name, row_type, many in (
        ("get_completed_totals", CompletedTotals, False),
        ("get_sales_graph", SalesGraphRow, True),
        ("get_top_selling_items", TopSellingItemRow, True),
    ):
        stack.enter_context(
            patch.object(
                AnalyticsRepository,
                name,
                wrap(getattr(AnalyticsRepository, name), row_type, many),
            )
        )


def install_dashboard_queries(stack: Any, benchmark: Any, prototype: bool) -> None:
    from app.modules.analytics.repo.queries import AnalyticsRepository

    original_exists = AnalyticsRepository.restaurant_exists

    @wraps(original_exists)
    async def scoped_exists(*args: Any, **kwargs: Any) -> Any:
        token = benchmark.PHASE.set("authorization")
        try:
            return await original_exists(*args, **kwargs)
        finally:
            benchmark.PHASE.reset(token)

    stack.enter_context(
        patch.object(AnalyticsRepository, "restaurant_exists", scoped_exists)
    )
    if prototype:
        install_prototype(stack, benchmark)


def main() -> int:
    prototype = "--prototype" in sys.argv
    if prototype:
        sys.argv.remove("--prototype")
    if any(
        arg in {"--scenarios", "--cache-state"}
        or arg.startswith(("--scenarios=", "--cache-state="))
        for arg in sys.argv[1:]
    ):
        raise ValueError(
            "Dashboard experiment owns scenario and cache-state selections"
        )
    spec = importlib.util.spec_from_file_location(
        "menu_benchmark", ROOT / "scripts/benchmark-menu-reads.py"
    )
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    original_metadata = benchmark.environment_metadata
    original_run = benchmark.run_benchmark
    original_client = benchmark.httpx.AsyncClient

    async def check_dashboard(response: Any) -> None:
        if (
            response.request.url.path.endswith("/analytics/dashboard")
            and response.status_code == 200
        ):
            await response.aread()
            body = response.json()
            if (
                body["orders"]["value"] != 100
                or Decimal(str(body["sales"]["value"])) != 2400
                or Decimal(str(body["average_order"]["value"])) != 24
                or sum(point["orders"] for point in body["sales_graph"]) != 700
            ):
                raise RuntimeError(
                    "Dashboard response disagrees with deterministic order history"
                )

    class CheckedClient(original_client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            hooks = kwargs.pop("event_hooks", {})
            hooks["response"] = [*hooks.get("response", []), check_dashboard]
            super().__init__(*args, event_hooks=hooks, **kwargs)

    def metadata(*args: Any) -> dict[str, Any]:
        result = original_metadata(*args)
        result["dashboard_experiment"] = {
            "version": "1.0.0",
            "report_date": datetime.now(UTC).astimezone().date().isoformat(),
            "server_timezone": str(datetime.now(UTC).astimezone().tzinfo),
            "script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
            "prototype_enabled": prototype,
            "production_behavior": "dashboard remains uncached",
            "response_assertions": "each response: 100 today orders, 2400 sales, 24 average, 700 orders over seven days",
            "limitations": "benchmark-only four aggregate Redis entries, 10-second absolute age, no write invalidation; not a production design or freshness approval",
        }
        return result

    def run(*args: Any) -> dict[str, Any]:
        args[1].dashboard_mode = "prototype" if prototype else "live"
        with patch.object(benchmark.httpx, "AsyncClient", CheckedClient):
            result = original_run(*args)
        result["benchmark"] = "restaurantos-dashboard-evaluation"
        result["metadata"]["workloads"] = {
            "dashboard": "100% authenticated GET dashboard; benchmark-only aggregate prototype on/off; no writes"
        }
        for row in result["results"]:
            row["cache_hit_ratio_label"] = (
                "all four aggregate results reused / dashboard GETs"
                if prototype
                else "N/A (live uncached dashboard)"
            )
        return result

    benchmark.environment_metadata = metadata
    benchmark.run_benchmark = run
    sys.argv.extend(
        [
            "--scenarios",
            "dashboard",
            "--cache-state",
            "warm" if prototype else "disabled",
        ]
    )
    return benchmark.main()


if __name__ == "__main__":
    raise SystemExit(main())
