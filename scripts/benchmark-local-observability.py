"""Run the declared Issue #65 baseline against newly owned local containers."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import platform
import re
import runpy
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from shutil import which
from threading import Event, Thread
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import psycopg
from sqlalchemy.engine import make_url
from test_support.disposable_postgres import disposable_database
from test_support.monitoring_environment import (
    ROOT,
    command,
    disposable_monitoring,
    require_local_engine,
    wait_until,
)
from validate import services

WARMUP = 30
DURATION = 90
ORDER_INTERVAL = 5
READ_INTERVAL = 0.5
DRAIN = 30
MATRIX = (False, True, True, False, False, True)
MONITORS = ("collector", "prometheus", "grafana", "loki", "tempo")
MONITORING_MEMORY_LIMIT_BYTES = 2_000_000_000
BACKEND = "restaurantos-issue65-backend:local"
FRONTEND = "restaurantos-issue65-frontend:local"


class BaselineFailure(RuntimeError):
    """An error with a sanitized, actionable reason."""


def docker(*args, **kwargs):
    return command("docker", *args, **kwargs)


def inspect(identifier, template):
    return json.loads(
        docker("inspect", "--format", "{{json " + template + "}}", identifier)
    )


def port(identifier, target):
    return int(docker("port", identifier, str(target)).rsplit(":", 1)[1])


def percentile(ordered, rank):
    return ordered[math.ceil(len(ordered) * rank / 100) - 1]


def latency(values):
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(ordered),
        **{f"p{p}": round(percentile(ordered, p), 4) for p in (50, 95, 99)},
        "max": round(ordered[-1], 4),
    }


def child(args, **kwargs):
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=120, check=False, **kwargs
    )
    if result.returncode:
        raise BaselineFailure(f"{Path(args[0]).name} setup exited {result.returncode}")


def launch(owners, name, *args):
    def cleanup():
        if docker("ps", "-aq", "--filter", "name=^/" + name + "$"):
            docker("rm", "--force", "--volumes", name)
        if docker("ps", "-aq", "--filter", "name=^/" + name + "$"):
            raise BaselineFailure("Application container cleanup incomplete")

    owners.callback(cleanup)
    return docker("run", "--pull=never", "-d", "--name", name, *args)


def prepare(
    owners,
    temporary,
    stack,
    settings,
    database,
    *,
    prefix="restaurantos-issue65",
    images=None,
    app_settings=None,
    loopback_host="localhost",
):
    backend_image, frontend_image = images or (BACKPIN, FRONTPIN)
    postgres = settings["TEST_POSTGRES_CONTAINER"]
    network = next(iter(inspect(postgres, ".NetworkSettings.Networks")))
    if not network.startswith("restaurantos-m6-"):
        raise BaselineFailure("Unexpected database network ownership")
    redis = docker(
        "ps",
        "-q",
        "--filter",
        "network=" + network,
        "--filter",
        "label=com.docker.compose.service=redis",
    )
    if stack is not None:
        stack.up()
        docker(
            "network",
            "connect",
            "--gw-priority",
            "-1",
            "--alias",
            "collector",
            network,
            stack.container("collector"),
        )
        owners.callback(
            docker, "network", "disconnect", network, stack.container("collector")
        )

    prefix += "-" + uuid4().hex[:12]
    api_name = prefix + "-api"
    enabled = str(stack is not None).lower()
    endpoint = "http://collector:4318"
    app_network = (
        "--network",
        network,
        "--log-opt",
        "max-size=5m",
        "--log-opt",
        "max-file=2",
    )
    frontend = launch(
        owners,
        prefix + "-frontend",
        *app_network,
        "-p",
        "127.0.0.1::3000",
        "-e",
        "API_URL=http://" + api_name + ":8000",
        "-e",
        "MONITORING_ENABLED=" + enabled,
        "-e",
        "MONITORING_ENDPOINT=" + endpoint,
        frontend_image,
    )
    web = f"http://{loopback_host}:{port(frontend, 3000)}"
    frontend_ip = inspect(frontend, ".NetworkSettings.Networks")[network]["IPAddress"]
    isolated = database.environment(settings)
    credentials = {
        key: isolated[key]
        for key in (
            "AUTH_JWT_SECRET",
            "AUTH_RATE_LIMIT_SECRET",
            "AUTH_COOKIE_SECURE",
            "AUTH_REFRESH_COOKIE_PATH",
        )
    }
    app_env = temporary / "application.env"
    app_env.write_text(
        "".join(
            f"{key}={value}\n"
            for key, value in {
                **credentials,
                "ENVIRONMENT": "development",
                "DATABASE_URL": make_url(database.async_url)
                .set(host="postgres", port=5432)
                .render_as_string(hide_password=False),
                "REDIS_URL": "redis://redis:6379/0",
                "AUTH_TRUSTED_ORIGINS": json.dumps([web]),
                "MONITORING_ENABLED": enabled,
                "MONITORING_ENDPOINT": endpoint,
                "MONITORING_TRUSTED_UPSTREAM_IPS": json.dumps([frontend_ip]),
                "MONITORING_WORKER_SLOT": "0",
                "MONITORING_BUSINESS_AGGREGATES_ENABLED": enabled,
                "MONITORING_BUSINESS_SALES_THB": enabled,
                **(app_settings or {}),
            }.items()
        ),
        encoding="utf-8",
    )
    app_env.chmod(0o600)
    api = launch(
        owners,
        api_name,
        *app_network,
        "--env-file",
        str(app_env),
        "-p",
        "127.0.0.1::8000",
        backend_image,
    )
    worker = launch(
        owners,
        prefix + "-worker",
        *app_network,
        "--env-file",
        str(app_env),
        "--no-healthcheck",
        backend_image,
        "python",
        "-m",
        "app.worker",
    )
    containers = {
        "api": api,
        "frontend": frontend,
        "worker": worker,
        "postgres": postgres,
        "redis": redis,
    }
    if stack:
        containers.update({service: stack.container(service) for service in MONITORS})
    return containers, f"http://{loopback_host}:{port(api, 8000)}", web


def fixture(client, api, web, account):
    def post(path, data, expected=(200, 201), method="POST"):
        r = client.request(method, api + path, json=data)
        if r.status_code not in expected:
            raise BaselineFailure(f"Fixture {method} step returned {r.status_code}")
        return r.json()

    post("/auth/login", account, (200,))
    restaurant = post("/api/restaurants", {"name": "Synthetic baseline branch"})["id"]
    menus = f"/restaurants/{restaurant}/menus"
    menu = post(menus, {"name": "Synthetic baseline menu"})["menu_id"]
    items = f"/menus/{menu}/items"
    item = None
    for i in range(4):
        row = post(items, {"name": f"Synthetic baseline item {i}", "price": "12.50"})
        if i == 0:
            item = row["menu_item_id"]
    inventory = f"/api/restaurants/{restaurant}/inventory"
    ingredients = inventory + "/ingredients"
    ingredient = post(
        ingredients,
        {
            "name": "Synthetic baseline piece",
            "unit": "piece",
            "opening_quantity": "1",
            "reorder_threshold": "1",
            "idempotency_key": "opening",
        },
    )["id"]
    post(
        f"/menu-items/{item}/recipe",
        {
            "inventory_tracking": True,
            "components": [{"ingredient_id": ingredient, "quantity": "1"}],
        },
        method="PUT",
    )
    return {
        "reads": (
            ("menu_list", api + menus),
            ("item_list", api + items),
            ("inventory_list", api + ingredients),
            ("dashboard", api + f"/api/restaurants/{restaurant}/analytics/dashboard"),
            ("menu_ssr", web + f"/restaurants/{restaurant}/menu"),
        ),
        "orders": api + f"/api/restaurants/{restaurant}/orders",
        "movements": api + ingredients + f"/{ingredient}/movements",
        "api": api,
        "item": item,
    }


def workload(client, other, fixture_data, run):
    begin = time.perf_counter() + 0.2
    run["workload_start"] = time.time() + 0.2
    duration = WARMUP + DURATION

    def pace(offset):
        time.sleep(max(0, begin + offset - time.perf_counter()))

    def attempt(
        lane, session, token, offset, label, method, url, expected, payload=None
    ):
        start = time.perf_counter()
        record = {
            "phase": "warmup" if offset < WARMUP else "measurement",
            "lane": lane,
            "slot": token,
            "operation": label,
            "method": method,
            "scheduled_seconds": offset,
            "start_seconds": round(start - begin, 6),
            "observed_unix_seconds": time.time(),
            "expected_status": expected,
        }
        response = None
        try:
            response = session.request(method, url, json=payload)
            record["status"] = response.status_code
            valid = response.status_code == expected
            if label == "menu_ssr":
                valid = valid and "Synthetic baseline menu" in response.text
            record["outcome"] = (
                "expected_conflict"
                if valid and expected == 409
                else "success"
                if valid
                else "unexpected"
            )
        except httpx.RequestError as error:
            record.update(outcome="unexpected", transport_error=type(error).__name__)
        record["milliseconds"] = round((time.perf_counter() - start) * 1000, 4)
        run["requests"].append(record)
        return response if record["outcome"] != "unexpected" else None

    def reads():
        routes = fixture_data["reads"]
        for index in range(int(duration / READ_INTERVAL)):
            offset = index * READ_INTERVAL
            pace(offset)
            label, url = routes[index % len(routes)]
            attempt("read", client, index, offset, label, "GET", url, 200)

    def commands():
        for index in range(duration // ORDER_INTERVAL):
            offset = index * ORDER_INTERVAL
            pace(offset)
            call = partial(attempt, "command", other, index, offset)
            key = f"order-{index}"
            receipt = call(
                "stock_receipt",
                "POST",
                fixture_data["movements"],
                201,
                {
                    "kind": "receipt",
                    "quantity": "1",
                    "reason": "Synthetic baseline receipt",
                    "idempotency_key": f"receipt-{index}",
                },
            )
            if receipt is None:
                continue
            draft = {
                "idempotency_key": key,
                "items": [{"menu_item_id": fixture_data["item"], "quantity": 1}],
            }
            created = call("order_create", "POST", fixture_data["orders"], 201, draft)
            if created is None:
                continue
            order_id = created.json()["order_id"]
            run["order_slots"][order_id] = index
            order = fixture_data["api"] + f"/api/orders/{order_id}"
            for status in ("SUBMITTED", "ACCEPTED", "PREPARING", "READY", "COMPLETED"):
                if (
                    call(
                        "order_" + status.lower(), "PUT", order, 200, {"status": status}
                    )
                    is None
                ):
                    break
            call(
                "order_create_conflict",
                "POST",
                fixture_data["orders"],
                409,
                {**draft, "notes": "Different synthetic replay"},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        read = pool.submit(reads)
        command_run = pool.submit(commands)
        read.result()
        command_run.result()
    pace(duration)
    run["workload_end"] = time.time()


def db_snapshot(connection):
    activity = connection.execute("""
        SELECT state, coalesce(wait_event_type, '') AS wait_event_type, count(*)
        FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
        GROUP BY state, wait_event_type ORDER BY state, wait_event_type
        """).fetchall()
    backlog = connection.execute("""
        SELECT consumer_name, status, count(*),
               extract(epoch from max(clock_timestamp()-created_at))::float8
        FROM event_deliveries GROUP BY consumer_name, status ORDER BY consumer_name, status
        """).fetchall()
    return {"connections": activity, "deliveries": backlog}


def resources(stop, database, containers, run):
    stats_parser = runpy.run_path(str(ROOT / "scripts/benchmark-monitoring.py"))
    from redis import Redis

    with (
        psycopg.connect(
            database.sync_url, autocommit=True, connect_timeout=5
        ) as connection,
        Redis.from_url(run["redis_url"], socket_timeout=2) as redis,
    ):
        while not stop.is_set():
            started = time.perf_counter()
            sample = {"time": time.time()}
            run["samples"].append(sample)
            try:
                raw = docker(
                    "stats",
                    "--no-stream",
                    "--no-trunc",
                    "--format",
                    "{{json .}}",
                    *containers.values(),
                    timeout=20,
                )
                mapping = {identifier: name for name, identifier in containers.items()}
                entries = {}
                for line in raw.splitlines():
                    row = stats_parser["stats_record"](line)
                    if row:
                        name = stats_parser["service_for_id"](mapping, row["ID"])
                        entries[name] = {
                            "working_set_bytes": stats_parser["memory_bytes"](
                                row["MemUsage"].split(" / ")[0]
                            ),
                            "cpu_percent_one_core": float(row["CPUPerc"].rstrip("%")),
                        }
                if entries.keys() != containers.keys():
                    raise BaselineFailure("Incomplete Docker stats sample")
                sample["containers"] = entries
                mem = docker("exec", containers["postgres"], "cat", "/proc/meminfo")
                sample["vm_memory_bytes"] = {
                    key: int(value) * 1024
                    for key, value in re.findall(
                        r"^(MemTotal|MemAvailable|SwapTotal|SwapFree):\s+(\d+) kB",
                        mem,
                        re.MULTILINE,
                    )
                }
                sample["postgres"] = db_snapshot(connection)
                sample["redis_stream_lengths"] = sorted(
                    redis.xlen(key) for key in redis.scan_iter(_type="stream")
                )
            except Exception as error:  # noqa: BLE001 - retain sanitized failed observations
                sample["error_type"] = type(error).__name__
            stop.wait(max(0, 5 - (time.perf_counter() - started)))


def storage(stack, containers):
    postgres = containers["postgres"]
    result = {
        "application_writable_layer_bytes": {
            name: int(
                docker("inspect", "--size", "--format", "{{.SizeRw}}", containers[name])
            )
            for name in ("api", "frontend", "worker", "redis")
        },
        "postgres_data_kib": int(
            docker("exec", postgres, "du", "-sk", "/var/lib/postgresql/data").split()[0]
        ),
        "vm_data_filesystem_kib": list(
            map(
                int,
                docker("exec", postgres, "df", "-kP", "/")
                .splitlines()[-1]
                .split()[1:4],
            )
        ),
    }
    if stack is not None:
        result["monitoring"] = runpy.run_path(
            str(ROOT / "scripts/benchmark-monitoring.py")
        )["disk"](stack, BACKPIN)
    return result


def telemetry(stack, start, end):
    selected = (
        "up|scrape_samples_scraped|prometheus_tsdb_head_series|"
        "restaurantos_(http_(duration_seconds_(bucket|count)|requests_total)|pool_(used|limit|acquiring|overflow|"
        "acquire_duration_seconds_(bucket|count)|acquire_failures_total)|"
        "worker_(collected_seconds|oldest_seconds|deliveries|operations_total))|"
        "otelcol_(receiver_(accepted|refused)_.*|exporter_(sent|send_failed|"
        "enqueue_failed)_.*|exporter_queue_(size|capacity)|processor_(refused|dropped)_.*)"
    )
    params = urlencode(
        {
            "query": '{__name__=~"' + selected + '"}',
            "start": start,
            "end": end,
            "step": 5,
        }
    )
    result = stack.query("prometheus", "/api/v1/query_range?" + params)
    if result["status"] != "success":
        raise BaselineFailure("Prometheus query did not succeed")
    return result["data"]["result"]


def export_evidence(containers, series):
    expected = {
        "otelcol_exporter_sent_spans",
        "otelcol_exporter_sent_log_records",
        "otelcol_receiver_accepted_metric_points",
        "restaurantos_http_requests_total",
        "restaurantos_pool_acquire_duration_seconds_count",
        "restaurantos_worker_operations_total",
    }
    observed = defaultdict(float)
    for row in series:
        name = row["metric"]["__name__"]
        observed[name] += float(row["values"][-1][1])
    warnings = {}
    for service in ("api", "frontend", "worker"):
        result = subprocess.run(
            ["docker", "logs", containers[service]],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        # Retain counts for known SDK failure signals, never raw container logs.
        warnings[service] = sum(
            bool(
                re.search(
                    r"telemetry_export_failed|telemetry shutdown failed|Failed to export|Queue full",
                    line,
                    re.IGNORECASE,
                )
            )
            for line in (result.stdout + result.stderr).splitlines()
        )
    return {
        "missing_positive_signals": sorted(
            name for name in expected if observed[name] <= 0
        ),
        "sdk_warning_lines": warnings,
    }


def durable(connection, run):
    expected = (WARMUP + DURATION) // ORDER_INTERVAL
    rows = connection.execute("""
        SELECT e.event_type, e.aggregate_type, e.aggregate_id, d.consumer_name,
               d.status, d.attempt_count, r.outcome,
               extract(epoch FROM pg_xact_commit_timestamp(r.xmin)
                                - pg_xact_commit_timestamp(e.xmin))::float8,
               extract(epoch FROM pg_xact_commit_timestamp(e.xmin))::float8
        FROM outbox_events e JOIN event_deliveries d USING (event_id)
        LEFT JOIN event_receipts r USING (event_id, consumer_name)
        ORDER BY e.occurred_at, e.event_id, d.consumer_name
        """).fetchall()
    effects = run["effects"]
    for (
        event,
        aggregate,
        identifier,
        consumer,
        status,
        attempts,
        outcome,
        seconds,
        event_commit,
    ) in rows:
        slot = run["order_slots"].get(int(identifier)) if aggregate == "order" else None
        phase = (
            ("warmup" if slot * ORDER_INTERVAL < WARMUP else "measurement")
            if slot is not None
            else (
                "measurement"
                if run["workload_start"] + WARMUP <= event_commit <= run["workload_end"]
                else "warmup_or_setup"
            )
        )
        effects.append(
            {
                "event": event,
                "consumer": consumer,
                "status": status,
                "attempts": attempts,
                "receipt_outcome": outcome,
                "commit_to_effect_seconds": seconds,
                "source_commit_unix_seconds": event_commit,
                "workflow_slot": slot,
                "phase": phase,
            }
        )
    count, sales = connection.execute(
        "SELECT coalesce(sum(order_count),0), coalesce(sum(sales),0) FROM analytics_daily_sales"
    ).fetchone()
    stock = connection.execute("SELECT quantity FROM inventory_balances").fetchone()[0]
    orders, completed = connection.execute(
        "SELECT count(*), count(*) FILTER (WHERE status='COMPLETED') FROM orders"
    ).fetchone()
    ledger = dict(
        connection.execute(
            "SELECT kind, count(*) FROM inventory_movements GROUP BY kind"
        )
    )
    alerts = connection.execute(
        "SELECT count(*) FROM alert_episodes WHERE opening_source='order_acceptance'"
    ).fetchone()[0]
    notifications = connection.execute(
        "SELECT count(*) FROM notification_stubs"
    ).fetchone()[0]
    run["reconciliation"] = {
        "order_count": orders,
        "completed_orders": completed,
        "projected_count": count,
        "projected_thb": str(sales),
        "balance_pieces": str(stock),
        "ledger": ledger,
        "projected_order_alert_openings": alerts,
        "notification_stubs": notifications,
        "delivery_outcomes": dict(Counter(row["status"] for row in effects)),
    }
    return (
        orders == completed == count == alerts == expected
        and sales == expected * 12.5
        and stock == 1
        and ledger.get("receipt") == expected
        and ledger.get("consumption") == expected
        and notifications >= expected
        and effects
        and all(
            row["status"] == "succeeded"
            and row["attempts"] == 1
            and row["receipt_outcome"] in {"processed", "skipped"}
            and row["commit_to_effect_seconds"] is not None
            and row["commit_to_effect_seconds"] >= 0
            for row in effects
        )
    )


def ready(client, url):
    try:
        return client.get(url, timeout=1).status_code == 200
    except httpx.RequestError:
        return False


def run_arm(run):
    if docker("ps", "-q"):
        raise BaselineFailure(
            "Stop other Docker containers before measuring this local baseline"
        )
    with ExitStack() as owners:
        temporary = Path(
            owners.enter_context(
                tempfile.TemporaryDirectory(prefix="restaurantos-issue65-")
            )
        )
        override = temporary / "benchmark.yaml"
        override.write_text(
            "services:\n  postgres:\n    command: [postgres, -c, track_commit_timestamp=on]\n"
        )
        settings = owners.enter_context(services(False, compose_override=override))
        database = owners.enter_context(
            disposable_database(
                prefix="issue65",
                test_url=settings["TEST_DATABASE_URL"],
            )
        )
        run["stage"] = "migration_and_seed"
        seed_settings = settings.copy()
        for key in tuple(seed_settings):
            if key.startswith(("AUTH_", "MONITORING_", "DATABASE_", "EVENT_WORKER_")):
                seed_settings.pop(key)
        isolated = database.environment(seed_settings)
        child(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=isolated,
        )
        account_id = uuid4()
        account = {
            "email": f"issue65-{account_id}@example.test",
            "password": f"Synthetic baseline {uuid4()}",
        }  # pragma: allowlist secret
        child(
            [
                sys.executable,
                str(ROOT / "frontend/tests/seed-auth.py"),
                "create",
                str(account_id),
            ],
            env=isolated,
            input=json.dumps(account),
        )
        run["stage"] = "startup"
        stack = (
            owners.enter_context(disposable_monitoring("container"))
            if run["enabled"]
            else None
        )
        containers, api, web = prepare(owners, temporary, stack, settings, database)
        run["images"] = {
            name: {
                "id": inspect(identifier, ".Image"),
                "reference": inspect(identifier, ".Config.Image"),
            }
            for name, identifier in containers.items()
        }
        run["stage"] = "readiness"
        with (
            httpx.Client(trust_env=False, timeout=4) as probe,
            httpx.Client(
                trust_env=False,
                timeout=4,
                headers={"Origin": web, "X-CSRF-Protection": "1"},
            ) as first,
            httpx.Client(
                trust_env=False,
                timeout=4,
                headers={"Origin": web, "X-CSRF-Protection": "1"},
            ) as second,
            psycopg.connect(
                database.sync_url, autocommit=True, connect_timeout=5
            ) as db,
        ):
            wait_until(
                lambda: ready(probe, api + "/ready"),
                timeout=45,
            )
            wait_until(
                lambda: ready(probe, web + "/login"),
                timeout=45,
            )
            if db.execute("SHOW track_commit_timestamp").fetchone()[0] != "on":
                raise BaselineFailure("Disposable commit tracking is disabled")
            run["migration_revision"] = db.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
            run["stage"] = "fixture"
            data = fixture(first, api, web, account)
            second.cookies.update(first.cookies)
            run["stage"] = "storage_before"
            run["storage_before"] = storage(stack, containers)
            run["stage"] = "workload"
            stop = Event()
            observer = Thread(
                target=resources,
                args=(
                    stop,
                    database,
                    containers,
                    {**run, "redis_url": settings["REDIS_URL"]},
                ),
                daemon=True,
            )
            observer.start()
            try:
                workload(first, second, data, run)
                deadline = time.perf_counter() + DRAIN
                while time.perf_counter() < deadline:
                    if not db.execute(
                        "SELECT EXISTS(SELECT 1 FROM event_deliveries WHERE status IN ('pending','processing'))"
                    ).fetchone()[0]:
                        break
                    time.sleep(0.2)
                if stack:
                    time.sleep(12)
            finally:
                stop.set()
                observer.join(timeout=30)
            run["stage"] = "reconciliation"
            healthy = durable(db, run)
            run["stage"] = "storage_after"
            run["storage_after"] = storage(stack, containers)
            run["container_states"] = {
                name: {
                    "running": (state := inspect(identifier, ".State"))["Running"],
                    "oom_killed": state["OOMKilled"],
                    "restarts": inspect(identifier, ".RestartCount"),
                }
                for name, identifier in containers.items()
            }
            if stack:
                run["stage"] = "telemetry_evidence"
                run["prometheus"] = telemetry(
                    stack, run["workload_start"] - 10, time.time()
                )
                run["exports"] = export_evidence(containers, run["prometheus"])
            run["stage"] = "checks"
            expected = int((WARMUP + DURATION) / READ_INTERVAL) + 8 * (
                (WARMUP + DURATION) // ORDER_INTERVAL
            )
            run["checks"] = {
                "durable_reconciled": bool(healthy),
                "all_requests_attempted": len(run["requests"]) == expected,
                "no_unexpected_requests": all(
                    row["outcome"] != "unexpected" for row in run["requests"]
                ),
                "resource_samples_complete": bool(run["samples"])
                and all("error_type" not in row for row in run["samples"]),
                "containers_stable": all(
                    row["running"] and not row["oom_killed"] and row["restarts"] == 0
                    for row in run["container_states"].values()
                ),
                "primary_signals_present": not stack
                or not run["exports"]["missing_positive_signals"],
            }
            if not all(run["checks"].values()):
                raise BaselineFailure("One or more repetition checks failed")
        run["stage"] = "cleanup"
    run["stage"] = "complete"


def summary(run):
    counts = Counter()
    timings = defaultdict(list)
    for row in run["requests"]:
        if row["phase"] == "measurement":
            counts[row["outcome"]] += 1
            if row["outcome"] != "unexpected":
                timings[row["operation"]].append(row["milliseconds"])
    freshness = defaultdict(list)
    for row in run["effects"]:
        if (
            row["phase"] == "measurement"
            and row["commit_to_effect_seconds"] is not None
        ):
            freshness[row["consumer"]].append(row["commit_to_effect_seconds"])
    valid = [row for row in run["samples"] if "vm_memory_bytes" in row]
    return {
        "outcomes": dict(counts),
        "latency_ms": {label: latency(samples) for label, samples in timings.items()},
        "commit_to_effect_seconds": {
            label: latency(samples) for label, samples in freshness.items()
        },
        "lowest_vm_available_bytes": min(
            (row["vm_memory_bytes"]["MemAvailable"] for row in valid), default=None
        ),
        "peak_monitoring_working_set_bytes": max(
            (
                sum(
                    row["containers"][service]["working_set_bytes"]
                    for service in MONITORS
                )
                for row in valid
                if run["enabled"]
            ),
            default=None,
        ),
        "peak_all_container_working_set_bytes": max(
            (
                sum(
                    service["working_set_bytes"]
                    for service in row["containers"].values()
                )
                for row in valid
            ),
            default=None,
        ),
    }


def local_objectives(run):
    """Evaluate the approved #65 limits for one full monitoring-on repetition."""
    measurements = [row for row in run["requests"] if row["phase"] == "measurement"]
    latency_limits = {
        "menu_list": (36, 100),
        "item_list": (36, 100),
        "inventory_list": (36, 100),
        "dashboard": (36, 100),
        "menu_ssr": (36, 200),
        "stock_receipt": (18, 150),
        "order_create": (18, 150),
        "order_submitted": (18, 150),
        "order_accepted": (18, 150),
        "order_preparing": (18, 150),
        "order_ready": (18, 150),
        "order_completed": (18, 150),
    }
    results = {}
    for operation, (minimum, limit) in latency_limits.items():
        samples = [
            row["milliseconds"]
            for row in measurements
            if row["operation"] == operation and row["outcome"] == "success"
        ]
        stats = latency(samples)
        results[operation] = {
            "observed": stats,
            "passed": len(samples) >= minimum
            and percentile(sorted(samples), 95) <= limit,
        }
    eligible = [row for row in measurements if row["outcome"] != "expected_conflict"]
    errors = sum(row["outcome"] == "unexpected" for row in eligible)
    results["unexpected_errors"] = {
        "attempts": len(eligible),
        "errors": errors,
        "passed": bool(eligible) and 100 * errors < len(eligible),
    }
    for consumer in ("analytics", "alerts", "notification_sink"):
        samples = [
            row["commit_to_effect_seconds"]
            for row in run["effects"]
            if row["phase"] == "measurement"
            and row["consumer"] == consumer
            and row["receipt_outcome"] == "processed"
        ]
        stats = latency(samples)
        results[consumer] = {
            "observed": stats,
            "passed": bool(samples)
            and percentile(sorted(samples), 95) <= 3
            and max(samples) <= 5,
        }
    peak = run["summary"]["peak_monitoring_working_set_bytes"]
    results["monitoring_memory"] = {
        "observed_bytes": peak,
        "passed": peak is not None and 0 < peak <= MONITORING_MEMORY_LIMIT_BYTES,
    }
    return results


def host_resources():
    if os.name == "nt":
        shell = which("powershell.exe")
        machine = command(
            shell,
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
        )
        return {"physical_memory_bytes": int(machine), "logical_cpus": os.cpu_count()}
    return {
        "physical_memory_bytes": os.sysconf("SC_PHYS_PAGES")
        * os.sysconf("SC_PAGE_SIZE"),
        "logical_cpus": os.cpu_count(),
    }


def driver_peak_bytes():
    if os.name == "nt":
        shell = which("powershell.exe")
        return int(
            command(
                shell,
                "-NoProfile",
                "-Command",
                f"(Get-Process -Id {os.getpid()}).PeakWorkingSet64",
            )
        )
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def write_report(report, path):
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(
        gzip.compress(
            (json.dumps(report, separators=(",", ":")) + "\n").encode(), mtime=0
        )
    )
    temporary.replace(path)


def main():
    global WARMUP, DURATION, BACKPIN, FRONTPIN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, required=True, help="new .json.gz report path"
    )
    parser.add_argument(
        "--smoke", action="store_true", help="one on arm, wiring checks only"
    )
    args = parser.parse_args()
    if args.report.suffixes[-2:] != [".json", ".gz"] or args.report.exists():
        parser.error("Choose a new .json.gz report path")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    require_local_engine()
    BACKPIN = docker("image", "inspect", "--format", "{{.Id}}", BACKEND)
    FRONTPIN = docker("image", "inspect", "--format", "{{.Id}}", FRONTEND)
    if args.smoke:
        WARMUP, DURATION = 5, 10
    report = {
        "schema": 1,
        "smoke": args.smoke,
        "run_start_unix_seconds": time.time(),
        "source_commit": command("git", "rev-parse", "HEAD"),
        "source_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in (
                "scripts/benchmark-local-observability.py",
                "scripts/validate.py",
                "docs/milestone9-observability/experiment-milestone9-issue65.md",
                "monitoring/images.lock.json",
                "docker-compose.test.yml",
            )
        },
        "docker_engine": docker(
            "info",
            "--format",
            "{{.ServerVersion}} {{.Architecture}} {{.NCPU}} {{.MemTotal}}",
        ),
        "docker_compose": docker("compose", "version", "--short"),
        "host": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            **host_resources(),
        },
        "settings": {
            "warmup_seconds": WARMUP,
            "measurement_seconds": DURATION,
            "drain_max_seconds": DRAIN,
            "read_interval_seconds": READ_INTERVAL,
            "workflow_interval_seconds": ORDER_INTERVAL,
            "acceptance_trace_sampling_fraction": 1.0,
            "business_collection_seconds": 30,
            "api_pool_size": 5,
            "api_pool_overflow": 10,
            "worker_pool_size": 6,
            "monitoring_memory_limit_bytes": MONITORING_MEMORY_LIMIT_BYTES,
            "docker_design_memory_bytes": 7_490_000_000,
            "api_build_id": BACKPIN,
            "frontend_build_id": FRONTPIN,
        },
        "repetitions": [],
    }
    for number, enabled in enumerate((True,) if args.smoke else MATRIX, 1):
        run = {
            "arm": number,
            "enabled": enabled,
            "stage": "isolation",
            "requests": [],
            "effects": [],
            "samples": [],
            "order_slots": {},
        }
        report["repetitions"].append(run)
        print(f"Arm {number}: monitoring {'on' if enabled else 'off'}", flush=True)
        cpu_start = time.process_time()
        started = time.perf_counter()
        try:
            run_arm(run)
            run["passed"] = True
        except Exception as error:  # noqa: BLE001 - retain sanitized failed observations
            run["passed"] = False
            run["failure"] = {"type": type(error).__name__}
            if isinstance(error, BaselineFailure):
                run["failure"]["reason"] = str(error)
        finally:
            run.pop("order_slots")
            run["driver_cpu_seconds"] = time.process_time() - cpu_start
            run["wall_seconds"] = time.perf_counter() - started
            run["driver_process_lifetime_peak_working_set_bytes"] = driver_peak_bytes()
            run["summary"] = summary(run)
            if run["passed"] and enabled and not args.smoke:
                objectives = run["local_objectives"] = local_objectives(run)
                if not all(result["passed"] for result in objectives.values()):
                    run["passed"] = False
                    run["failure"] = {
                        "reason": "Approved local objectives or memory budget missed"
                    }
            write_report(report, args.report)
        print(
            f"Arm {number}: {run.get('failure', 'passed')} ({run['stage']})", flush=True
        )
    return 0 if all(run["passed"] for run in report["repetitions"]) else 1


if __name__ == "__main__":
    sys.exit(main())
