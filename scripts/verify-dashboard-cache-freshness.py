"""Compare live/prototype dashboard behavior after a real committed order delete."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
from test_support.disposable_postgres import disposable_database
from validate import services

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def probe(database, environment, benchmark, mode):
    from tests.support.owned_redis import owned_redis

    with owned_redis() as (_, redis_port):
        settings = benchmark.isolated_settings(database, redis_port)
        import app.core.config as application_config

        application_config.get_settings = lambda: settings
        benchmark.run_alembic()
        seeded = benchmark.seed_data(database)
        benchmark.seed_dashboard_history(database, seeded)
        with psycopg.connect(database.sync_url) as connection:
            order_id = connection.execute(
                "SELECT order_id FROM orders WHERE restaurant_id=%s AND created_at::date=%s ORDER BY order_id LIMIT 1",
                (seeded["restaurant_id"], datetime.now(UTC).astimezone().date()),
            ).fetchone()[0]
            stock_before = connection.execute(
                "SELECT sum(quantity) FROM inventory_balances"
            ).fetchone()[0]
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        explicit = settings.model_dump(mode="json")
        for name in ("auth_jwt_secret", "auth_rate_limit_secret", "redis_url"):
            explicit[name] = getattr(settings, name).get_secret_value()
        worker_environment = {
            **environment,
            "_RESTAURANTOS_BENCHMARK_CONFIG": json.dumps(
                {
                    "settings": explicit,
                    "port": port,
                    "cache_state": "disabled",
                    "dashboard": mode,
                }
            ),
        }
        server = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/benchmark-menu-reads.py"), "--serve"],
            cwd=ROOT,
            env=worker_environment,
            stdin=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        async def execute():
            base = f"http://127.0.0.1:{port}"
            await benchmark.wait_for_server(base, server)
            async with httpx.AsyncClient(
                base_url=base,
                headers={"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"},
                timeout=30,
            ) as client:
                login = await client.post(
                    "/auth/login",
                    json={"email": seeded["email"], "password": seeded["password"]},
                )
                if login.status_code != 200:
                    raise RuntimeError("Freshness probe login failed")
                path = f"/api/restaurants/{seeded['restaurant_id']}/analytics/dashboard"

                async def values():
                    response = await client.get(path)
                    if response.status_code != 200:
                        raise RuntimeError("Freshness probe dashboard read failed")
                    body = response.json()
                    return {
                        "orders": body["orders"]["value"],
                        "sales": str(body["sales"]["value"]),
                        "seven_day_orders": sum(
                            point["orders"] for point in body["sales_graph"]
                        ),
                    }

                before = await values()
                if before["orders"] != 100 or before["seven_day_orders"] != 700:
                    raise RuntimeError("Unexpected seeded dashboard values")
                forbidden = await client.delete(f"/api/orders/{order_id}")
                if forbidden.status_code != 403:
                    raise RuntimeError("Manager hard-delete permission changed")
                async with httpx.AsyncClient(
                    base_url=base,
                    headers={
                        "Origin": "http://localhost:3000",
                        "X-CSRF-Protection": "1",
                    },
                    timeout=30,
                ) as owner_client:
                    owner_login = await owner_client.post(
                        "/auth/login",
                        json={
                            "email": "benchmark-owner@example.test",
                            "password": seeded["password"],
                        },
                    )
                    if owner_login.status_code != 200:
                        raise RuntimeError("Freshness Owner login failed")
                    removed = await owner_client.delete(f"/api/orders/{order_id}")
                    if removed.status_code != 204:
                        raise RuntimeError(
                            f"Permitted Owner deletion failed: HTTP {removed.status_code}"
                        )
                immediate = await values()
                expected = 100 if mode == "prototype" else 99
                if immediate["orders"] != expected:
                    raise RuntimeError("Unexpected immediate dashboard freshness")
                await asyncio.sleep(10.1)
                expired = await values()
                if expired["orders"] != 99 or expired["seven_day_orders"] != 699:
                    raise RuntimeError(
                        "Dashboard did not reflect committed deletion after expiry"
                    )
                return {
                    "mode": mode,
                    "manager_delete_status": forbidden.status_code,
                    "owner_delete_status": removed.status_code,
                    "before": before,
                    "after_committed_delete": immediate,
                    "after_10_second_expiry": expired,
                }

        try:
            with benchmark.socket_poll_guard() as expired_sockets:
                result = asyncio.run(execute())
                result["expired_windows_socket_poll_count"] = expired_sockets[0]
        finally:
            try:
                server.communicate(input="stop\n", timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
                raise RuntimeError(
                    "Freshness API required forced termination"
                ) from None
            if server.returncode != 0:
                raise RuntimeError("Freshness API exited unsuccessfully")
        with psycopg.connect(database.sync_url) as connection:
            stock_after = connection.execute(
                "SELECT sum(quantity) FROM inventory_balances"
            ).fetchone()[0]
            audit = connection.execute(
                "SELECT count(*) FROM audit_entries WHERE action='order.deleted'"
            ).fetchone()[0]
        if stock_after != stock_before or audit != 1:
            raise RuntimeError("Deletion did not preserve stock/transactional audit")
        result.update(
            stock_quantity_before=str(stock_before),
            stock_quantity_after=str(stock_after),
            committed_delete_audit_count=audit,
        )
        return result


def main():
    sys.path.insert(0, str(BACKEND))
    spec = importlib.util.spec_from_file_location(
        "menu_benchmark", ROOT / "scripts/benchmark-menu-reads.py"
    )
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    results = []
    with services(False) as environment:
        for mode in ("live", "prototype"):
            with disposable_database(
                prefix="restaurantos_dashboard",
                test_url=environment["TEST_DATABASE_URL"],
            ) as database:
                results.append(probe(database, environment, benchmark, mode))
            print(
                f"{mode}: committed deletion/freshness/stock/audit and owned cleanup passed",
                flush=True,
            )
    report = {
        "schema_version": 1,
        "benchmark": "dashboard-freshness-evaluation",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(
            (ROOT / "scripts/benchmark-menu-reads.py").read_bytes()
        ).hexdigest(),
        "prototype_script_sha256": hashlib.sha256(
            (ROOT / "scripts/benchmark-dashboard-cache.py").read_bytes()
        ).hexdigest(),
        "dataset": "700 historical completed paid orders, 1400 item snapshots; one permitted unprocessed legacy order deleted through the real API",
        "results": results,
    }
    destination = ROOT / "docs/milestone7/benchmarks/dashboard-freshness.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Evidence: {destination}", flush=True)


if __name__ == "__main__":
    main()
