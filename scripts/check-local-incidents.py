"""Exercise #66 incidents against new local containers and a guarded database."""

import argparse
import hashlib
import json
import runpy
import subprocess
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import psycopg
import yaml
from test_support.disposable_postgres import disposable_database
from test_support.monitoring_environment import (
    ROOT,
    command,
    disposable_monitoring,
    require_local_engine,
    wait_until,
)
from validate import services

SUPPORT = runpy.run_path(str(ROOT / "scripts/benchmark-local-observability.py"))
OBSERVABILITY = runpy.run_path(str(ROOT / "scripts/check-api-observability.py"))
INCIDENTS = (
    "api_failure",
    "database_exhaustion",
    "redis_outage",
    "worker_stopped",
    "repeated_job_failure",
    "monitoring_outage",
)
POOL_SIZE = 2
IMAGE_TAGS = ("restaurantos-backend:m6", "restaurantos-frontend:m9")
RECEIVER = "http://alert-receiver:8080/alerts"


class IncidentFailure(RuntimeError):
    """Safe failure detail for the report."""


def require(value, message):
    if not value:
        raise IncidentFailure(message)
    return value


def poll(check, *, timeout=180, action=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        if action:
            action()
        else:
            time.sleep(1)
    raise IncidentFailure("Observation deadline exceeded")


def docker(*arguments):
    return command("docker", *arguments)


def pin_images(owners, identifiers):
    aliases = []
    run_id = uuid4().hex
    for kind, identifier in zip(("backend", "frontend"), identifiers, strict=True):
        alias = f"restaurantos-issue66-{kind}:{run_id}"
        docker("image", "tag", identifier, alias)
        owners.callback(docker, "image", "rm", alias)
        aliases.append(alias)
    return tuple(aliases)


def utc():
    return datetime.now(UTC).isoformat()


class Rehearsal:
    def __init__(self, db, env, client, api, fixture, containers, stack, account):
        self.db = db
        self.env = env
        self.client = client
        self.api = api
        self.data = fixture
        self.containers = containers
        self.stack = stack
        self.account = account
        self.orders = []
        provisions = yaml.safe_load(
            (
                ROOT / "monitoring/grafana/provisioning/alerting/local-incidents.yaml"
            ).read_text(encoding="utf-8")
        )
        self.rule_queries = {
            rule["uid"]: rule["data"][0]["model"]["expr"]
            for rule in provisions["groups"][0]["rules"]
        }

    def request(self, method, url, expected, **kwargs):
        response = self.client.request(method, url, **kwargs)
        require(
            response.status_code == expected,
            f"{method} returned {response.status_code}, expected {expected}",
        )
        return response

    def refresh_api_port(self):
        # Docker can allocate a new host port when a random binding is restarted.
        previous = self.api
        host = previous.rsplit(":", 1)[0]
        self.api = f"{host}:{SUPPORT['port'](self.containers['api'], 8000)}"
        for path in ("api", "orders", "movements"):
            self.data[path] = self.data[path].replace(previous, self.api, 1)
        self.data["reads"] = tuple(
            (name, url.replace(previous + "/", self.api + "/", 1))
            for name, url in self.data["reads"]
        )

    def traffic(self):
        for _ in range(4):
            self.request("GET", self.api + "/api/test", 200)
        time.sleep(0.5)

    def draft(self):
        return {
            "idempotency_key": "issue66-" + uuid4().hex,
            "items": [{"menu_item_id": self.data["item"], "quantity": 1}],
        }

    def order(self):
        self.request(
            "POST",
            self.data["movements"],
            201,
            json={
                "kind": "receipt",
                "quantity": "1",
                "reason": "Synthetic incident stock receipt",
                "idempotency_key": uuid4().hex,
            },
        )
        response = self.request("POST", self.data["orders"], 201, json=self.draft())
        order_id = response.json()["order_id"]
        path = self.api + f"/api/orders/{order_id}"
        for status in ("SUBMITTED", "ACCEPTED", "PREPARING", "READY", "COMPLETED"):
            self.request("PUT", path, 200, json={"status": status})
        self.orders.append(order_id)
        return order_id

    def wait_effects(self):
        poll(
            lambda: (
                not self.db.execute(
                    "SELECT EXISTS (SELECT 1 FROM event_deliveries WHERE status IN ('pending','processing'))"
                ).fetchone()[0]
            )
        )

    def reconcile(self):
        self.wait_effects()
        require(
            self.db.execute(
                "SELECT count(*) FROM event_deliveries WHERE status <> 'succeeded'"
            ).fetchone()[0]
            == 0,
            "Delivery failed after recovery",
        )
        orders = self.db.execute(
            "SELECT count(*), coalesce(sum(total), 0) FROM orders WHERE status = 'COMPLETED'"
        ).fetchone()
        projection = self.db.execute(
            "SELECT count(*), coalesce(sum(total), 0) FROM analytics_order_contributions WHERE state = 'completed'"
        ).fetchone()
        counts = self.db.execute(
            """
            SELECT (SELECT count(*) FROM event_deliveries),
                   (SELECT count(*) FROM event_receipts),
                   (SELECT count(*) FROM inventory_movements WHERE kind = 'consumption')
            """
        ).fetchone()
        require(
            orders == projection
            and orders[0] == len(self.orders)
            and counts[0] == counts[1]
            and counts[2] == len(self.orders),
            "Order, projection, inventory or receipt reconciliation failed",
        )
        return {
            "completed_orders": orders[0],
            "completed_total": str(orders[1]),
            "deliveries": counts[0],
            "receipts": counts[1],
            "consumptions": counts[2],
        }

    def prom(self, expr):
        return self.stack.query(
            "prometheus", "/api/v1/query?" + urlencode({"query": expr})
        )["data"]["result"]

    def capture(self):
        return json.loads(self.stack.internal(RECEIVER))

    def sustained(self, rule, expected_labels):
        query = self.rule_queries["ros-local-" + rule]
        return [
            row
            for row in self.prom(f"({query}) == 2")
            if all(
                row["metric"].get(key) == value
                for key, value in expected_labels.items()
            )
        ]

    def wait_sustained(self, result, rule, labels, *, timeout, action=None):
        try:
            return poll(
                lambda: self.sustained(rule, labels), timeout=timeout, action=action
            )
        finally:
            match = ",".join(
                [f'signal="{rule}"', *(f'{key}="{val}"' for key, val in labels.items())]
            )
            result["phase_samples"] = self.prom(f"ros_alert:phase{{{match}}}[5m]")

    def notification(self, name, status, after, *, timeout=180, action=None, **labels):
        def search():
            captures = self.capture()
            for document in captures[after:]:
                for alert in document["alerts"]:
                    if (
                        alert["status"] == status
                        and alert["labels"].get("alertname") == name
                        and all(
                            alert["labels"].get(key) == val
                            for key, val in labels.items()
                        )
                    ):
                        expected_group = {
                            key: val
                            for key, val in alert["labels"].items()
                            if key
                            in {
                                "alertname",
                                "role",
                                "worker_slot",
                                "consumer",
                                "source",
                            }
                        }
                        require(
                            document["groupLabels"] == expected_group,
                            "Webhook grouping differs from the operational identity",
                        )
                        return alert
            return None

        return poll(search, timeout=timeout, action=action)

    def alert_recovered(self, start, firing, *, action=None, timeout=445):
        labels = dict(firing["labels"])
        name = labels.pop("alertname")
        resolved = self.notification(
            name, "resolved", start, action=action, timeout=timeout, **labels
        )
        require(
            resolved["fingerprint"] == firing["fingerprint"],
            "Alert identity changed during recovery",
        )
        observed = [
            row
            for item in self.capture()[start:]
            for row in item["alerts"]
            if row["fingerprint"] == firing["fingerprint"] and row["status"] == "firing"
        ]
        require(len(observed) == 1, "Grouped local alert was sent more than once")
        return {
            "firing": firing,
            "resolved": resolved,
            "firing_deliveries": len(observed),
        }

    def stored_failure(self, request_id, forbidden):
        def log():
            rows = self.stack.query(
                "loki",
                "/loki/api/v1/query_range?"
                + urlencode(
                    {
                        "query": '{service_name="restaurantos-api"} | request_id="'
                        + request_id
                        + '"',
                        "limit": 10,
                    }
                ),
            )["data"]["result"]
            return rows or None

        rows = poll(log, timeout=60)
        encoded = json.dumps(rows)
        require(
            "server_error" in encoded and forbidden not in encoded,
            "Failure log privacy or correlation check failed",
        )
        metadata = [row["stream"] for row in rows]
        metadata.extend(
            value[2] for row in rows for value in row["values"] if len(value) > 2
        )
        trace_id = next(
            (labels["trace_id"] for labels in metadata if labels.get("trace_id")), None
        )
        require(trace_id, "No trace ID on the correlated failure log")

        def span():
            try:
                trace = self.stack.query("tempo", "/api/traces/" + trace_id)
            except HTTPError as error:
                if error.code == 404:
                    return None
                raise
            for entry in OBSERVABILITY["spans_in"](trace):
                attrs = {attr["key"]: attr["value"] for attr in entry["attributes"]}
                if attrs.get("request_id", {}).get("stringValue") == request_id:
                    require(
                        forbidden not in json.dumps(entry),
                        "Trace contained the private failure canary",
                    )
                    require(
                        attrs["outcome"]["stringValue"] == "server_error",
                        "Trace had unexpected outcome",
                    )
                    return {
                        "request_id": request_id,
                        "trace_id": trace_id,
                        "route": attrs["http.route"]["stringValue"],
                        "server_seconds": round(
                            (
                                int(entry["endTimeUnixNano"])
                                - int(entry["startTimeUnixNano"])
                            )
                            / 1_000_000_000,
                            3,
                        ),
                    }
            return None

        return poll(span, timeout=60)

    @contextmanager
    def rejected_write(self, table, operation):
        # Both callers choose hardcoded fixture tables and verbs. No application
        # route, package, or persisted migration contains the fault.
        self.db.execute(
            """
            CREATE FUNCTION incident66_reject() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'internal-issue66-private-canary' USING ERRCODE = '40001';
            END
            $$
            """
        )
        try:
            self.db.execute(
                f"CREATE TRIGGER incident66_reject BEFORE {operation} ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION incident66_reject()"
            )
            try:
                yield
            finally:
                self.db.execute(f"DROP TRIGGER incident66_reject ON {table}")
        finally:
            self.db.execute("DROP FUNCTION incident66_reject()")

    def api_failure(self, result):
        poll(
            lambda: self.prom("ros_alert:api_error_ratio"),
            timeout=150,
            action=self.traffic,
        )
        start = len(self.capture())
        initial_orders = self.db.execute("SELECT count(*) FROM orders").fetchone()[0]
        request_id = "issue66-api-" + uuid4().hex
        draft = self.draft()

        def fail():
            self.request("GET", self.api + "/api/restaurants", 200)
            for _ in range(2):
                response = self.request(
                    "POST",
                    self.data["orders"],
                    500,
                    json=draft,
                    headers={"X-Request-ID": request_id, "Connection": "close"},
                )
                require(
                    "internal-issue66-private-canary" not in response.text,
                    "Failure leaked the private canary",
                )
                result["fault_requests"] = result.get("fault_requests", 0) + 1
            time.sleep(0.5)

        with self.rejected_write("orders", "INSERT"):
            result["sustained_api_signal"] = self.wait_sustained(
                result,
                "api",
                {},
                timeout=420,
                action=fail,
            )
            firing = self.notification(
                "Sustained API errors", "firing", start, timeout=60, action=fail
            )
            require(
                self.db.execute("SELECT count(*) FROM orders").fetchone()[0]
                == initial_orders,
                "Faulted order persisted",
            )
        result["correlation"] = self.stored_failure(
            request_id, "internal-issue66-private-canary"
        )
        result["notification"] = {"firing": firing}
        try:
            # The five-minute error lookback and two-minute healthy period
            # precede asynchronous evaluation and webhook delivery.
            result["notification"] = self.alert_recovered(
                start, firing, action=self.traffic, timeout=600
            )
        finally:
            result["recovery_samples"] = self.prom(
                'ros_alert:qualified{signal="api"}[4m]'
            )
        self.request("GET", self.api + "/auth/me", 200)
        result["business"] = self.reconcile()

    def database_exhaustion(self, result):
        start = len(self.capture())
        read = self.api + "/api/restaurants"
        request_id = "issue66-pool-" + uuid4().hex

        def stall():
            with httpx.Client(
                trust_env=False, timeout=185, cookies=self.client.cookies
            ) as client:
                return client.get(read).status_code

        with ThreadPoolExecutor(max_workers=POOL_SIZE) as workers:
            with self.db.transaction():
                self.db.execute("LOCK TABLE restaurants IN ACCESS EXCLUSIVE MODE")
                waiting = [workers.submit(stall) for _ in range(POOL_SIZE)]

                def overlap():
                    self.db.execute("SELECT pg_stat_clear_snapshot()")
                    count = self.db.execute(
                        """
                        SELECT count(*) FROM pg_stat_activity
                        WHERE datname=current_database() AND %s = ANY(pg_blocking_pids(pid))
                          AND query LIKE '%%FROM restaurants%%'
                        """,
                        (self.db.info.backend_pid,),
                    ).fetchone()[0]
                    return count == POOL_SIZE

                poll(overlap, timeout=25)
                result["overlapping_sessions"] = POOL_SIZE
                poll(
                    lambda: self.prom('ros_alert:pool_ratio{role="api"} == 1'),
                    timeout=35,
                )

                def timeout():
                    start_time = time.monotonic()
                    res = self.client.get(
                        self.api + "/ready", headers={"X-Request-ID": request_id}
                    )
                    elapsed = time.monotonic() - start_time
                    result["failure_http_status"] = res.status_code
                    result["max_failure_seconds"] = round(elapsed, 3)
                    require(
                        res.status_code == 503 and elapsed <= 5,
                        "Pool exhaustion was not a bounded server failure",
                    )

                timeout()
                poll(
                    lambda: self.prom('ros_alert:pool_timeouts_2m{role="api"} >= 1'),
                    timeout=35,
                )
                firing = self.notification(
                    "Database pool saturation", "firing", start, timeout=105, role="api"
                )
            require(
                all(job.result() == 200 for job in waiting),
                "Blocked API reads failed to recover",
            )
        result["correlation"] = self.stored_failure(request_id, "QueuePool limit")
        require(
            result["correlation"]["server_seconds"] <= 2.25,
            "Server readiness span exceeded its two-second budget plus tolerance",
        )
        result["notification"] = self.alert_recovered(
            start, firing, action=self.traffic
        )
        poll(lambda: self.prom('restaurantos_pool_used{role="api"} == 0'), timeout=30)
        self.request("GET", self.api + "/auth/me", 200)
        result["business"] = self.reconcile()

    @contextmanager
    def stopped(self, service):
        container = self.containers[service]
        since = time.monotonic()
        docker("stop", "-t", "15", container)
        seconds = time.monotonic() - since
        try:
            require(seconds < 20, "Service shutdown exceeded its exercise budget")
            yield round(seconds, 3)
        finally:
            docker("start", container)

    def redis_outage(self, result):
        start = len(self.capture())
        self.wait_effects()
        menu = self.data["reads"][0][1]
        before = self.request("GET", menu, 200).json()
        require(
            self.request("GET", menu, 200).json() == before,
            "Healthy cached read changed",
        )
        with self.stopped("redis"):
            require(
                self.request("GET", menu, 200).json() == before,
                "PostgreSQL cache fallback changed the response",
            )
            self.request("GET", self.api + "/auth/me", 200)
            with httpx.Client(
                trust_env=False, timeout=5, headers=self.client.headers
            ) as new_session:
                login = new_session.post(self.api + "/auth/login", json=self.account)
                require(login.status_code == 200, "Login failed in Redis fallback mode")
                require(
                    new_session.get(self.api + "/auth/me").status_code == 200,
                    "Fallback login failed to establish an authenticated session",
                )
            result["authenticated_during_redis_outage"] = True
            self.order()
            backlog = self.prom('ros_alert:unfinished{consumer="analytics"}')
            if not backlog or float(backlog[0]["value"][1]) == 0:
                poll(
                    lambda: self.prom('ros_alert:unfinished{consumer="analytics"} > 0')
                )
            result["sustained_backlog"] = self.wait_sustained(
                result,
                "backlog",
                {"consumer": "analytics"},
                timeout=150,
            )
            firing = self.notification(
                "Old unfinished work", "firing", start, timeout=65, consumer="analytics"
            )
            result["redis_signal"] = poll(
                lambda: self.prom(
                    'restaurantos_redis_operations_total{outcome!="success"} > 0'
                ),
                timeout=45,
            )
        result["business"] = self.reconcile()
        result["notification"] = self.alert_recovered(start, firing)

    def worker_stopped(self, result):
        start = len(self.capture())
        self.wait_effects()
        with self.stopped("worker") as seconds:
            result["shutdown_seconds"] = seconds
            self.order()
            result["sustained_backlog"] = self.wait_sustained(
                result,
                "backlog",
                {"consumer": "analytics"},
                timeout=150,
            )
            firing = self.notification(
                "Old unfinished work", "firing", start, timeout=65, consumer="analytics"
            )
            result["unfinished"] = require(
                self.prom('ros_alert:unfinished_age{consumer="analytics"} > 10'),
                "No durable age while worker stopped",
            )
            result["missing_worker"] = self.notification(
                "Missing operational telemetry", "firing", start, source="worker"
            )
            with self.stopped("collector"):
                result["missing_collector"] = self.notification(
                    "Missing operational telemetry", "firing", start, source="collector"
                )
                require(
                    not self.prom(
                        'ros_alert:phase{signal="backlog",consumer="analytics"}'
                    ),
                    "Backlog remained eligible through a Collector outage",
                )
                require(
                    not any(
                        alert["fingerprint"] == firing["fingerprint"]
                        and alert["status"] == "resolved"
                        for document in self.capture()[start:]
                        for alert in document["alerts"]
                    ),
                    "Grafana falsely resolved an incident during a telemetry gap",
                )
            poll(
                lambda: self.prom(
                    'ros_alert:phase{signal="backlog",consumer="analytics"} == 2'
                )
            )
            result["collector_recovered"] = self.alert_recovered(
                start, result["missing_collector"]
            )
        result["business"] = self.reconcile()
        result["missing_worker_recovered"] = self.alert_recovered(
            start, result["missing_worker"]
        )
        result["notification"] = self.alert_recovered(start, firing)

    def event_cli(self, *args):
        result = subprocess.run(
            [sys.executable, "-m", "app.modules.events.cli", *map(str, args)],
            cwd=ROOT / "backend",
            env=self.env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        require(result.returncode == 0, "Event CLI failed")
        return json.loads(result.stdout)

    def repeated_job_failure(self, result):
        start = len(self.capture())
        with self.rejected_write("analytics_order_contributions", "INSERT"):
            self.order()
            delivery = self.db.execute(
                """
                SELECT d.id FROM event_deliveries d JOIN outbox_events e ON e.event_id=d.event_id
                WHERE d.consumer_name='analytics' AND e.event_type='order.completed.v1'
                  AND e.aggregate_id=%s
                """,
                (str(self.orders[-1]),),
            ).fetchone()[0]
            poll(
                lambda: self.prom('ros_alert:retries_5m{consumer="analytics"} >= 1'),
                timeout=45,
            )
            firing = self.notification(
                "Repeated job failures", "firing", start, consumer="analytics"
            )
            before = self.event_cli("inspect", delivery)
            require(
                before["status"] == "failed" and len(before["attempts"]) == 4,
                "Expected three retries and one terminal attempt",
            )
            result["before"] = before
        result["replay"] = self.event_cli(
            "replay", delivery, "--reason", "Removed disposable failing trigger"
        )
        result["business"] = self.reconcile()
        after = self.event_cli("inspect", delivery)
        require(
            after["status"] == "succeeded"
            and after["event_id"] == before["event_id"]
            and after["correlation_id"] == before["correlation_id"]
            and after["attempts"][:4] == before["attempts"]
            and len(after["attempts"]) == 5
            and after["replays"][0]["replay_id"] == result["replay"]["replay_id"],
            "Replay lost identities, prior attempts or the successful effect",
        )
        result["after"] = after
        result["notification"] = self.alert_recovered(start, firing)

    def monitoring_outage(self, result):
        start = len(self.capture())
        history_start = int(time.time())
        self.traffic()
        with self.stopped("collector") as seconds:
            result["collector_shutdown_seconds"] = seconds
            poll(lambda: self.prom('up{job="collector-telemetry"} == 0'))
            self.order()
            result["effects_without_collector"] = self.reconcile()
            result["memory_without_collector"] = self.memory_snapshot("api", "worker")
            result["app_shutdown_without_collector"] = {}
            for service in ("api", "worker"):
                with self.stopped(service) as elapsed:
                    exit_code = SUPPORT["inspect"](
                        self.containers[service], ".State.ExitCode"
                    )
                    require(
                        exit_code in {0, 143},
                        "Application process required a forced stop",
                    )
                    result["app_shutdown_without_collector"][service] = {
                        "seconds": elapsed,
                        "exit_code": exit_code,
                    }
            self.refresh_api_port()
            with httpx.Client(trust_env=False, timeout=3) as probe:
                poll(lambda: SUPPORT["ready"](probe, self.api + "/ready"), timeout=30)
            self.request("GET", self.api + "/auth/me", 200)
            self.order()
            result["effects_after_restart_without_collector"] = self.reconcile()
            firing = self.notification(
                "Missing operational telemetry", "firing", start, source="collector"
            )
            require(
                not self.prom("ros_alert:delivery_fresh"),
                "Collector outage retained a fresh signal",
            )
            require(
                not self.prom("ros_alert:api_fresh"),
                "Collector outage retained a fresh API signal",
            )
        result["collector_notification"] = self.alert_recovered(
            start, firing, action=self.traffic
        )
        with self.stopped("tempo"), self.stopped("loki"):
            names = 'job=~"tempo|loki"'
            poll(lambda: len(self.prom(f"up{{{names}}} == 0")) == 2)
            self.order()
            result["effects_without_destinations"] = self.reconcile()
            result["destination_failures"] = poll(
                lambda: self.prom(
                    '{job="collector-self",__name__=~"otelcol_exporter_send_failed_(spans|log_records)(_total)?"} > 0'
                ),
                timeout=95,
                action=self.traffic,
            )
            result["memory_without_destinations"] = self.memory_snapshot(
                "api", "worker", "collector"
            )
            result["export_queues"] = require(
                self.prom(
                    '{job="collector-self",__name__=~"otelcol_exporter_queue_(size|capacity)"}'
                ),
                "Collector queue evidence unavailable",
            )
            require(
                not self.prom(
                    "otelcol_exporter_queue_size > ignoring (__name__) otelcol_exporter_queue_capacity"
                ),
                "Collector queue exceeded its capacity",
            )
        poll(lambda: len(self.prom(f"up{{{names}}} == 1")) == 2)
        with self.stopped("grafana"):
            self.order()
            result["effects_without_grafana"] = self.reconcile()
        wait_until(lambda: self.stack.grafana("/api/health"))
        result["scrape_history"] = self.stack.query(
            "prometheus",
            "/api/v1/query_range?"
            + urlencode(
                {
                    "query": 'up{job=~"collector-telemetry|loki|tempo"}',
                    "start": history_start,
                    "end": int(time.time()),
                    "step": 5,
                }
            ),
        )["data"]["result"]
        require(
            len(result["scrape_history"]) == 3
            and all(
                {"0", "1"} <= {value for _, value in series["values"]}
                and series["values"][-1][1] == "1"
                for series in result["scrape_history"]
            ),
            "Stored scrape history did not retain all three outages and recoveries",
        )
        result["business"] = self.reconcile()
        result["resources"] = {
            service: {
                "oom_killed": SUPPORT["inspect"](container, ".State.OOMKilled"),
                "memory_limit_bytes": SUPPORT["inspect"](
                    container, ".HostConfig.Memory"
                ),
            }
            for service, container in self.containers.items()
        }
        require(
            not any(row["oom_killed"] for row in result["resources"].values()),
            "A container was OOM-killed",
        )

    def memory_snapshot(self, *services):
        return dict(
            zip(
                services,
                docker(
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{.MemUsage}}",
                    *(self.containers[service] for service in services),
                ).splitlines(),
                strict=True,
            )
        )


def run(report, selected, inject_failure):
    report["stage"] = "local Docker preflight"
    require_local_engine()
    images = tuple(
        docker("image", "inspect", "--format", "{{.Id}}", tag) for tag in IMAGE_TAGS
    )
    report["images"] = dict(zip(IMAGE_TAGS, images, strict=True))
    report["source"] = command("git", "rev-parse", "HEAD")
    report["configuration_sha256"] = {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in (
            ROOT / "monitoring/alert-signals.yaml",
            ROOT / "monitoring/compose.yaml",
            ROOT / "monitoring/otel-collector.yaml",
            ROOT / "monitoring/grafana/provisioning/alerting/local-incidents.yaml",
            ROOT / "monitoring/grafana/provisioning/alerting/local-notifications.yaml",
            Path(__file__).resolve(),
        )
    }
    projects = []
    # Verify resources by their project ownership labels after all owners exit.
    try:
        with ExitStack() as owners:
            pinned_images = pin_images(owners, images)
            temp = Path(
                owners.enter_context(
                    tempfile.TemporaryDirectory(prefix="restaurantos-issue66-")
                )
            )
            report["stage"] = "disposable PostgreSQL and Redis"
            settings = owners.enter_context(services(False))
            project = SUPPORT["inspect"](
                settings["TEST_POSTGRES_CONTAINER"], ".Config.Labels"
            )["com.docker.compose.project"]
            projects.append(project)
            database = owners.enter_context(
                disposable_database(
                    prefix="issue66", test_url=settings["TEST_DATABASE_URL"]
                )
            )
            database_settings = database.environment(settings)
            report["stage"] = "migration and fixture account"
            SUPPORT["child"](
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT / "backend",
                env=database_settings,
            )
            actor = uuid4()
            account = {
                "email": f"issue66-{actor}@example.test",
                "password": f"Synthetic incident {uuid4()}",
            }  # pragma: allowlist secret
            SUPPORT["child"](
                [
                    sys.executable,
                    str(ROOT / "frontend/tests/seed-auth.py"),
                    "create",
                    str(actor),
                ],
                env=database_settings,
                input=json.dumps(account),
            )
            report["stage"] = "monitoring and application startup"
            stack = owners.enter_context(disposable_monitoring("container"))
            projects.append(stack.project)
            container_ids, api, web = SUPPORT["prepare"](
                owners,
                temp,
                stack,
                settings,
                database,
                prefix="restaurantos-issue66",
                images=pinned_images,
                loopback_host="127.0.0.1",
                app_settings={
                    "DATABASE_POOL_SIZE": str(POOL_SIZE),
                    "DATABASE_MAX_OVERFLOW": "0",
                    "DATABASE_POOL_TIMEOUT_SECONDS": "1",
                    "AUTH_ACCESS_SECONDS": "3600",
                    "EVENT_WORKER_MAX_ATTEMPTS": "4",
                    "MONITORING_BUSINESS_AGGREGATES_ENABLED": "false",
                },
            )
            receiver_path = ROOT / "scripts/test_support/local_alert_receiver.py"
            container_ids["receiver"] = SUPPORT["launch"](
                owners,
                stack.project + "-receiver",
                "--network",
                stack.project + "_monitoring",
                "--network-alias",
                "alert-receiver",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--memory",
                "33554432",
                "--memory-swap",
                "33554432",
                "--pids-limit",
                "16",
                "--mount",
                f"type=bind,src={receiver_path},dst=/receiver.py,readonly",
                "--no-healthcheck",
                pinned_images[0],
                "python",
                "-B",
                "/receiver.py",
            )
            with (
                httpx.Client(
                    trust_env=False,
                    timeout=5,
                    headers={"Origin": web, "X-CSRF-Protection": "1"},
                ) as client,
                psycopg.connect(
                    database.sync_url, autocommit=True, connect_timeout=5
                ) as session,
            ):
                poll(lambda: SUPPORT["ready"](client, api + "/ready"), timeout=45)
                report["database_revision"] = session.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()[0]
                report["stage"] = "fixture and rule provisioning"
                fixture = SUPPORT["fixture"](client, api, web, account)
                rehearsal = Rehearsal(
                    session,
                    database_settings,
                    client,
                    api,
                    fixture,
                    container_ids,
                    stack,
                    account,
                )
                try:
                    provisioned = stack.grafana("/api/v1/provisioning/alert-rules")
                    report["rules"] = sorted(row["uid"] for row in provisioned)
                    require(
                        set(report["rules"])
                        == {
                            "ros-local-api",
                            "ros-local-pool",
                            "ros-local-backlog",
                            "ros-local-jobs",
                            "ros-local-telemetry",
                        },
                        "Unexpected provisioned rule identities",
                    )
                    poll(
                        lambda: len(rehearsal.prom("ros_alert:unfinished")) == 3,
                        timeout=60,
                    )
                    rehearsal.capture()
                    if inject_failure:
                        report["stage"] = "intentional failure"
                        raise IncidentFailure("Intentional failure after provisioning")
                    for name in selected:
                        report["stage"] = name
                        print(f"Running {name}", flush=True)
                        evidence = report["cases"][name] = {"started_at": utc()}
                        getattr(rehearsal, name)(evidence)
                        evidence["finished_at"] = utc()
                        print(f"PASS: {name}", flush=True)
                finally:
                    try:
                        report["notifications"] = rehearsal.capture()
                    except (OSError, RuntimeError, ValueError):
                        report["notification_capture_unavailable"] = True
    finally:
        report["owned_resources_removed"] = all(
            not docker(
                kind,
                "ls",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + project,
            )
            for project in projects
            for kind in ("container", "network", "volume")
        )
        require(report["owned_resources_removed"], "Owned Compose resources remain")
    report["stage"] = "complete"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--incident", choices=INCIDENTS, action="append")
    parser.add_argument("--inject-failure", action="store_true")
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {"started_at": utc(), "cases": {}}
    try:
        run(report, args.incident or INCIDENTS, args.inject_failure)
    except Exception as error:  # noqa: BLE001 - retain sanitized evidence on any exercise failure
        report["failure"] = (
            str(error) if isinstance(error, IncidentFailure) else type(error).__name__
        )
        # Only store fault stage and the sanitized, bounded evidence gathered so far.
        frames = traceback.extract_tb(error.__traceback__)
        report["failure_locations"] = [
            f"{Path(frame.filename).name}:{frame.lineno}" for frame in frames
        ]
        return 1
    finally:
        report["finished_at"] = utc()
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(
            f"{report['stage']}: {report.get('failure', 'passed')} ({args.report})",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
