"""Inspect real FastAPI signals in the owned #58 stores; no developer databases.

Print checks only. This deliberately does not write an issue verification report.
"""

import argparse
import base64
import copy
import json
import math
import secrets
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from test_support.disposable_postgres import disposable_database
from test_support.monitoring_environment import (
    ROOT,
    command,
    disposable_monitoring,
    wait_until,
)
from validate import services

PROBE_SPAN_ID = "1234567890abcdef"  # pragma: allowlist secret


def prom(stack, expression):
    return stack.query(
        "prometheus", "/api/v1/query?" + urlencode({"query": expression})
    )["data"]["result"]


def spans_in(trace):
    return [
        span
        for batch in trace.get("batches", trace.get("resourceSpans", []))
        for scope in batch.get(
            "scopeSpans", batch.get("instrumentationLibrarySpans", [])
        )
        for span in scope["spans"]
    ]


def collector_probe(stack, canary):
    """Spoofed service.name still undergoes the complete API privacy policy."""
    trace_id = uuid4().hex
    now = time.time_ns()

    def attr(key, value):
        return {
            "key": key,
            "value": {"intValue" if isinstance(value, int) else "stringValue": value},
        }

    attributes = [
        attr("http.route", "/health"),
        attr("http.request.method", "GET"),
        attr("http.response.status_code", 200),
        attr("outcome", "success"),
        attr("request_id", "collector-policy-probe"),
        attr("db.statement", canary),
    ]
    resource = {
        "attributes": [
            attr("service.name", "restaurantos-api"),
            attr("credential", canary),
        ]
    }
    scope = {"name": canary, "version": canary, "attributes": [attr("private", canary)]}
    span = {
        "traceId": trace_id,
        "spanId": PROBE_SPAN_ID,
        "name": "HTTP request",
        "kind": 2,
        "startTimeUnixNano": str(now),
        "endTimeUnixNano": str(now + 1000000),
        "attributes": attributes,
        "status": {"code": 2, "message": canary},
        "traceState": "private=" + canary,
        "events": [{"name": canary, "timeUnixNano": str(now)}],
    }
    payloads = {
        "traces": {
            "resourceSpans": [
                {
                    "resource": resource,
                    "schemaUrl": canary,
                    "scopeSpans": [
                        {"scope": scope, "schemaUrl": canary, "spans": [span]}
                    ],
                }
            ]
        },
        "logs": {
            "resourceLogs": [
                {
                    "resource": resource,
                    "schemaUrl": canary,
                    "scopeLogs": [
                        {
                            "scope": scope,
                            "schemaUrl": canary,
                            "logRecords": [
                                {
                                    "timeUnixNano": str(now),
                                    "traceId": trace_id,
                                    "spanId": PROBE_SPAN_ID,
                                    "body": {"stringValue": canary},
                                    "severityText": canary,
                                    "eventName": canary,
                                    "attributes": attributes,
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }
    metric_attributes = copy.deepcopy(attributes)
    metric_attributes[1] = attr("http.request.method", "TRACE")
    counter = {
        "name": "restaurantos.http.requests",
        "description": canary,
        "unit": "1",
        "sum": {
            "aggregationTemporality": 2,
            "isMonotonic": True,
            "dataPoints": [
                {
                    "startTimeUnixNano": str(now - 1000000),
                    "timeUnixNano": str(now),
                    "asInt": "1",
                    "attributes": metric_attributes,
                }
            ],
        },
    }
    unknown = copy.deepcopy(counter)
    unknown["name"] = canary
    raw_path = copy.deepcopy(counter)
    raw_path["sum"]["dataPoints"][0]["attributes"][0] = attr("http.route", "/" + canary)
    payloads["metrics"] = {
        "resourceMetrics": [
            {
                "resource": resource,
                "schemaUrl": canary,
                "scopeMetrics": [
                    {
                        "scope": scope,
                        "schemaUrl": canary,
                        "metrics": [counter, unknown, raw_path],
                    }
                ],
            }
        ]
    }
    for signal, payload in payloads.items():
        request = Request(
            f"http://127.0.0.1:{stack.port('collector', 4318)}/v1/{signal}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
            assert response.status == 200
    trace = wait_until(lambda: stack.query("tempo", "/api/traces/" + trace_id))
    assert spans_in(trace)
    assert canary not in json.dumps(trace)
    logs = wait_until(
        lambda: stack.query(
            "loki",
            "/loki/api/v1/query_range?"
            + urlencode(
                {
                    "query": '{service_name="restaurantos-api"} | request_id="collector-policy-probe"',
                    "limit": 10,
                }
            ),
        )["data"]["result"]
    )
    assert trace_id in json.dumps(logs) and canary not in json.dumps(logs)
    wait_until(
        lambda: prom(
            stack,
            'restaurantos_http_requests_total{service_name="restaurantos-api",http_request_method="TRACE"}',
        )
    )
    assert canary not in json.dumps(prom(stack, '{service_name="restaurantos-api"}'))
    assert not prom(stack, '{__name__=~".*CANARY59.*"}')
    print(
        "PASS: Collector independently strips spoofed API body, exception/status, SQL, scope/resource/schema metadata and events",
        flush=True,
    )


def inspect(stack, result):
    trace_id, canary = result["trace_id"], result["canary"]
    capacity = result["capacity"]
    outcomes = {
        200: "success",
        401: "authentication",
        403: "forbidden",
        404: "not_found",
        422: "validation",
        500: "server_error",
    }
    expected_points = {
        (path, method, str(status), outcome)
        for path, method in capacity["operations"]
        for status, outcome in outcomes.items()
    }
    expected_categories = {
        "success",
        "validation",
        "forbidden",
        "not_found",
        "conflict",
        "authentication",
        "rate_limit",
        "server_error",
        "cancelled",
    }

    def complete_snapshot():
        rows = prom(
            stack, 'restaurantos_http_requests_total{service_name="restaurantos-api"}'
        )
        return (
            rows
            if expected_categories <= {row["metric"]["outcome"] for row in rows}
            and expected_points
            <= {
                (
                    row["metric"]["http_route"],
                    row["metric"]["http_request_method"],
                    row["metric"]["http_response_status_code"],
                    row["metric"]["outcome"],
                )
                for row in rows
            }
            else None
        )

    metrics = wait_until(complete_snapshot)
    assert all(
        set(row["metric"])
        <= {
            "__name__",
            "instance",
            "job",
            "exported_job",
            "service_name",
            "http_route",
            "http_request_method",
            "http_response_status_code",
            "outcome",
        }
        for row in metrics
    ), sorted({key for row in metrics for key in row["metric"]})
    for row in metrics:
        assert row["metric"]["exported_job"] == "restaurantos-api"
    assert {
        row["metric"]["http_route"]
        for row in metrics
        if row["metric"]["http_route"].startswith("/api/orders/")
    } == {"/api/orders/{order_id}"}
    probe = [
        row
        for row in metrics
        if row["metric"]["http_route"] == capacity["route"]
        and row["metric"]["http_request_method"] == capacity["method"]
        and row["metric"]["http_response_status_code"] == "500"
    ]
    assert len(probe) == 1 and float(probe[0]["value"][1]) == 1, (
        "idle re-export inflated cumulative counters"
    )
    histogram = prom(
        stack,
        'restaurantos_http_duration_seconds_bucket{service_name="restaurantos-api"}',
    )
    assert len({row["metric"]["le"] for row in histogram}) == 13
    quantiles = []
    for q in (0.5, 0.95, 0.99):
        rows = prom(
            stack,
            f'histogram_quantile({q}, sum by (le) (restaurantos_http_duration_seconds_bucket{{service_name="restaurantos-api"}}))',
        )
        assert rows and math.isfinite(float(rows[0]["value"][1]))
        quantiles.append(float(rows[0]["value"][1]))
    inflight = prom(
        stack, 'restaurantos_http_inflight{service_name="restaurantos-api"}'
    )
    assert inflight and all(float(row["value"][1]) == 0 for row in inflight)
    assert prom(
        stack,
        'restaurantos_http_last_observation_seconds{service_name="restaurantos-api"}',
    )

    def anchored_trace():
        result = stack.query("tempo", "/api/traces/" + trace_id)
        return (
            result
            if any(
                attribute.get("key") == "request_id"
                and attribute.get("value", {}).get("stringValue") == "issue59-business"
                for span in spans_in(result)
                for attribute in span.get("attributes", [])
            )
            else None
        )

    trace = wait_until(anchored_trace)
    spans = spans_in(trace)
    assert spans and all(s["name"] == "HTTP request" for s in spans), (
        "API spans missing or unexpected names"
    )

    def completed_logs():
        rows = stack.query(
            "loki",
            "/loki/api/v1/query_range?"
            + urlencode(
                {
                    "query": '{service_name="restaurantos-api"}',
                    "limit": 1000,
                }
            ),
        )["data"]["result"]
        encoded = json.dumps(rows)
        return (
            rows
            if trace_id in encoded
            and "issue59-business" in encoded
            and "issue59-cancelled" in encoded
            else None
        )

    logs = wait_until(completed_logs)
    values = [value for stream in logs for value in stream["values"]]
    assert len(values) < 1000
    encoded_logs = json.dumps(logs)
    assert trace_id in encoded_logs
    assert "issue59-business" in encoded_logs
    anchor = next(
        span
        for span in spans
        if any(
            attribute.get("key") == "request_id"
            and attribute.get("value", {}).get("stringValue") == "issue59-business"
            for attribute in span.get("attributes", [])
        )
    )
    span_id = anchor["spanId"]
    span_id = span_id.lower() if len(span_id) == 16 else base64.b64decode(span_id).hex()
    assert any(
        stream["stream"].get("request_id") == "issue59-business"
        and stream["stream"].get("span_id") == span_id
        and stream["stream"].get("trace_id") == trace_id
        for stream in logs
    ), "stored log/span correlation mismatch"
    # query_range extracts structured metadata into its result labels. Inspect
    # the index series separately: result labels are not an index inventory.
    indexed = stack.query(
        "loki",
        "/loki/api/v1/series?"
        + urlencode(
            {
                "match[]": '{service_name="restaurantos-api"}',
            }
        ),
    )["data"]
    assert indexed and all(set(series) == {"service_name"} for series in indexed), (
        indexed
    )
    assert canary not in json.dumps([metrics, histogram, inflight, trace, logs]), (
        "canary found in stored telemetry"
    )
    assert all(not span.get("events") and not span.get("links") for span in spans)
    print(
        f"PASS: stored API metrics ({len(metrics)} series, {capacity['groups']} capacity groups after quiet re-export), P50/P95/P99 {quantiles}, zero in-flight, correlated Loki/Tempo and absent canary",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container-smoke", action="store_true")
    parser.add_argument("--image", default="restaurantos-backend:m6")
    args = parser.parse_args()
    if args.container_smoke:
        container_smoke(args.image)
        return
    with disposable_monitoring("host") as stack, services(False) as environment:
        stack.up()
        with disposable_database(
            prefix="restaurantos_api_otel", test_url=environment["TEST_DATABASE_URL"]
        ) as database:
            isolated = database.environment(environment)
            isolated["TEST_MONITORING_ENDPOINT"] = (
                f"http://127.0.0.1:{stack.port('collector', 4318)}"
            )
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT / "backend",
                env=isolated,
                check=True,
            )
            workload = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/integration/test_http_observability.py::test_stored_api_signals_workload",
                    "-q",
                    "-s",
                ],
                cwd=ROOT / "backend",
                env=isolated,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            marker = "API_OBSERVABILITY_RESULT="
            result = next(
                (
                    json.loads(line.split(marker, 1)[1])
                    for line in workload.stdout.splitlines()
                    if marker in line
                ),
                None,
            )
            if workload.returncode or result is None:
                print(workload.stdout)
                print(workload.stderr)
                raise RuntimeError("API telemetry workload failed")
            inspect(stack, result)
            collector_probe(stack, result["canary"])
    print("PASS: disposable monitoring and PostgreSQL/Redis cleanup", flush=True)


def container_smoke(image):
    """Production runtime image -> private Collector DNS; no DB use/migration."""
    canary = "CANARY59_CONTAINER_PRIVATE_COOKIE_QUERY"
    trace_id = uuid4().hex
    with disposable_monitoring("container") as stack:
        stack.up()
        name = stack.project + "-api"
        environment = stack.directory / "api.env"
        environment.write_text(
            "\n".join(
                [
                    "DATABASE_URL=postgresql+asyncpg://unused:unused@127.0.0.1/observability_test",  # pragma: allowlist secret
                    "AUTH_JWT_SECRET=" + secrets.token_urlsafe(48),
                    "AUTH_RATE_LIMIT_SECRET=" + secrets.token_urlsafe(48),
                    "MONITORING_ENABLED=true",
                    "MONITORING_ENDPOINT=http://collector:4318",
                    "MONITORING_EXPORT_INTERVAL_MS=1000",
                    'MONITORING_TRUSTED_UPSTREAM_IPS=["127.0.0.1"]',
                    "REDIS_URL=redis://127.0.0.1:1/0",
                ]
            )
        )
        try:
            command(
                "docker",
                "run",
                "--detach",
                "--name",
                name,
                "--network",
                stack.project + "_monitoring",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "256m",
                "--memory-swap",
                "256m",
                "--pids-limit",
                "128",
                "--env-file",
                str(environment),
                image,
            )
            wait_until(
                lambda: command(
                    "docker",
                    "exec",
                    name,
                    "python",
                    "-c",
                    "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health',timeout=2).read(); print('ready')",
                )
            )
            code = (
                "from urllib.request import Request,urlopen; "
                f"r=Request('http://127.0.0.1:8000/health?password={canary}',headers="
                + repr(
                    {
                        "traceparent": f"00-{trace_id}-1234567890abcdef-01",
                        "Cookie": "private=" + canary,
                        "baggage": canary,
                        "X-Request-ID": "issue59-container",
                    }
                )
                + ") ; "
                "assert urlopen(r,timeout=2).status==200"
            )
            command("docker", "exec", name, "python", "-c", code)
            wait_until(
                lambda: prom(
                    stack,
                    'restaurantos_http_requests_total{service_name="restaurantos-api",http_route="/health"}',
                )
            )
            trace = wait_until(lambda: stack.query("tempo", "/api/traces/" + trace_id))
            logs = wait_until(
                lambda: stack.query(
                    "loki",
                    "/loki/api/v1/query_range?"
                    + urlencode(
                        {
                            "query": '{service_name="restaurantos-api"} | request_id="issue59-container"',
                            "limit": 10,
                        }
                    ),
                )["data"]["result"]
            )
            assert spans_in(trace) and trace_id in json.dumps(logs)
            output = subprocess.run(
                ["docker", "logs", name],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            local = output.stdout + output.stderr
            assert canary not in json.dumps([trace, logs, local])
            print(
                "PASS: production API image exports via private collector:4318 to all three stores, correlated and canary-free",
                flush=True,
            )
        finally:
            subprocess.run(
                ["docker", "rm", "--force", "--volumes", name],
                check=True,
                capture_output=True,
                timeout=30,
            )
            environment.unlink(missing_ok=True)
    print("PASS: private container smoke cleanup", flush=True)


if __name__ == "__main__":
    main()
