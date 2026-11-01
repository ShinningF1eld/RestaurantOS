"""Isolated monitoring smoke, restart and destination-outage acceptance."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import time
from itertools import pairwise
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from uuid import uuid4

import yaml
from test_support.monitoring_environment import (
    ROOT,
    command,
    disposable_monitoring,
    wait_until,
)
from test_support.processes import stop_processes

spec = importlib.util.spec_from_file_location(
    "monitoring_producer", ROOT / "scripts/generate-monitoring-telemetry.py"
)
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)


def build_generator() -> str:
    return command(
        "docker",
        "build",
        "--quiet",
        "-f",
        "monitoring/synthetic/Dockerfile",
        ".",
        timeout=300,
    ).splitlines()[-1]


def generate(stack, duration: int, seed: str, *, rate: int = 5, warmup: int = 0):
    args = [
        "--duration",
        str(duration),
        "--warmup",
        str(warmup),
        "--rate",
        str(rate),
        "--seed",
        seed,
        "--canary",
        "--hold-seconds",
        "10",
    ]
    name = stack.project + "-generator"
    if stack.state["mode"] == "host":
        cmd = [
            sys.executable,
            str(ROOT / "scripts/generate-monitoring-telemetry.py"),
            "--endpoint",
            f"http://127.0.0.1:{stack.port('collector', 4318)}",
            *args,
        ]
    else:
        image = build_generator()
        cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            stack.project + "_monitoring",
            "--memory",
            "128000000",
            "--memory-swap",
            "128000000",
            "--pids-limit",
            "64",
            "--read-only",
            "--cap-drop",
            "ALL",
            image,
            "--endpoint",
            "http://collector:4318",
            *args,
        ]
    child = subprocess.Popen(
        cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        output, _ = child.communicate(timeout=duration + 90)
        result = json.loads(output.splitlines()[-1])
        if child.returncode or not result["complete"]:
            raise RuntimeError("Synthetic producer incomplete: " + json.dumps(result))
        return result
    finally:
        stop_processes(child)
        if stack.state["mode"] == "container":
            cleanup = subprocess.run(
                ["docker", "rm", "-f", "-v", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if cleanup.returncode and "No such container" not in cleanup.stderr:
                raise RuntimeError("Producer cleanup failed")


def prom(stack, expression: str):
    return stack.query(
        "prometheus", "/api/v1/query?" + urlencode({"query": expression})
    )["data"]["result"]


def exact_metric(stack, name: str, value: float):
    def check():
        result = prom(stack, name)
        return (
            result
            if result
            and math.isclose(float(result[0]["value"][1]), value, abs_tol=1e-8)
            else None
        )

    return wait_until(check, 120)


def trace_spans(trace):
    return [
        span
        for batch in trace.get("batches", trace.get("resourceSpans", []))
        for scope in batch.get(
            "scopeSpans", batch.get("instrumentationLibrarySpans", [])
        )
        for span in scope["spans"]
    ]


def hex_id(value: str) -> str:
    return value.lower() if len(value) in (16, 32) else base64.b64decode(value).hex()


def reconcile(stack, result: dict) -> dict:
    count = result["generated_operations"]
    metrics = exact_metric(stack, "restaurantos_synthetic_operations_total", count)
    total = ((count + 1) // 2 * 10 + count // 2 * 25) / 1000
    metrics += exact_metric(stack, "restaurantos_synthetic_duration_seconds_sum", total)
    metrics += exact_metric(
        stack, "restaurantos_synthetic_duration_seconds_count", count
    )
    query = (
        'sum(count_over_time({service_name="restaurantos-monitoring-synthetic"}[2h]))'
    )

    def logs_complete():
        response = stack.query(
            "loki", "/loki/api/v1/query?" + urlencode({"query": query})
        )
        rows = response["data"]["result"]
        return rows if rows and float(rows[0]["value"][1]) == count else None

    wait_until(logs_complete, 120)
    seen = set()
    start = int(result["started_unix_seconds"]) - 1
    end = math.ceil(result["started_unix_seconds"] + result["elapsed_seconds"]) + 1
    for lower in range(start, end, 10):
        path = "/api/search?" + urlencode(
            {
                "q": '{resource.service.name="restaurantos-monitoring-synthetic"}',
                "start": lower,
                "end": min(lower + 10, end),
                "limit": 1000,
            }
        )
        response = stack.query("tempo", path)
        rows = response.get("traces", [])
        if len(rows) >= 1000:
            raise RuntimeError("Trace query truncated; narrow the fixture window")
        seen.update(row["traceID"] for row in rows)
    if len(seen) != count:
        raise RuntimeError(f"Trace reconciliation mismatch: {len(seen)} != {count}")
    tid, sid, child = producer.identities(result["seed"], 1)
    trace = wait_until(lambda: stack.query("tempo", "/api/traces/" + tid), 120)
    spans = {hex_id(span["spanId"]): span for span in trace_spans(trace)}
    assert len(spans) == 2 and hex_id(spans[child]["parentSpanId"]) == sid
    logs = stack.query(
        "loki",
        "/loki/api/v1/query_range?"
        + urlencode(
            {
                "query": '{service_name="restaurantos-monitoring-synthetic"} | trace_id="'
                + tid
                + '"',
                "limit": 10,
            }
        ),
    )
    assert tid in json.dumps(logs) and sid in json.dumps(logs)
    assert "SYNTHETIC_PRIVATE_CANARY" not in json.dumps([metrics, logs, trace])
    return {
        "operations": count,
        "logs": count,
        "traces": len(seen),
        "spans_expected": count * 2,
        "histogram_sum_seconds": total,
        "trace_parentage_and_log_link": True,
        "queried_canary_absent": True,
    }


def inspect_stack(stack):
    result = {}
    for name in ("collector", "prometheus", "grafana", "loki", "tempo"):
        data = json.loads(command("docker", "inspect", stack.container(name)))[0]
        if (
            data["State"]["OOMKilled"]
            or data["RestartCount"]
            or not data["State"]["Running"]
        ):
            raise RuntimeError(name + " failed or restarted")
        result[name] = {
            "memory_limit": data["HostConfig"]["Memory"],
            "memory_plus_swap_limit": data["HostConfig"]["MemorySwap"],
            "user": data["Config"]["User"],
            "oom": False,
            "restarts": 0,
            "image_id": data["Image"],
        }
    assert sum(row["memory_limit"] for row in result.values()) == 2_000_000_000
    return result


def smoke(stack):
    try:
        stack.grafana("/api/datasources", authenticated=False)
        raise RuntimeError("Anonymous data-source access allowed")
    except HTTPError as error:
        assert error.code == 401
    result = generate(stack, 3, "smoke-" + uuid4().hex[:8])
    verified = reconcile(stack, result)
    return {
        "producer": result,
        "reconciliation": verified,
        "containers": inspect_stack(stack),
    }


def restart(stack):
    result = generate(stack, 3, "restart-" + uuid4().hex[:8])
    reconcile(stack, result)
    stack.down()
    stack.up()
    # Collector's process-local cache legitimately resets; durable Prometheus
    # history must remain, queried explicitly over the prior time window.
    historical = stack.query(
        "prometheus",
        "/api/v1/query?"
        + urlencode(
            {"query": "max_over_time(restaurantos_synthetic_operations_total[15m])"}
        ),
    )
    assert float(historical["data"]["result"][0]["value"][1]) == 15
    tid, _, _ = producer.identities(result["seed"], 1)
    assert len(trace_spans(stack.query("tempo", "/api/traces/" + tid))) == 2
    logs = stack.query(
        "loki",
        "/loki/api/v1/query_range?"
        + urlencode(
            {
                "query": '{service_name="restaurantos-monitoring-synthetic"}',
                "limit": 100,
            }
        ),
    )
    assert sum(len(row["values"]) for row in logs["data"]["result"]) == 15
    return {
        "three_store_restart_persistence": True,
        "collector_cache_reset_expected": True,
    }


def outage(stack, seconds=180):
    report = {}
    for destination in ("loki", "tempo"):
        stack.compose("stop", destination)
        generated = generate(stack, seconds, "outage-" + destination)
        # HTTP acknowledgement is Collector admission, not destination delivery.
        failures = prom(
            stack, '{__name__=~"otelcol_exporter_.*(send_failed|enqueue_failed).*"}'
        )
        assert any(
            float(row["value"][1]) > 0
            and row["metric"].get("exporter") == "otlp_http/" + destination
            for row in failures
        )
        state = json.loads(command("docker", "inspect", stack.container("collector")))[
            0
        ]
        assert (
            state["State"]["Running"]
            and not state["State"]["OOMKilled"]
            and state["RestartCount"] == 0
        )
        stack.compose("start", destination)
        wait_until(
            lambda destination=destination: stack.internal(
                "http://"
                + destination
                + (":3100/ready" if destination == "loki" else ":3200/ready")
            )
        )
        wait_until(
            lambda destination=destination: (
                stack.grafana(
                    "/api/datasources/uid/restaurantos-" + destination + "/health"
                )["status"]
                == "OK"
            )
        )
        report[destination] = {
            "failure_or_queue_signal": True,
            "collector_survived": True,
            "collector_restarts": state["RestartCount"],
            "collector_memory_limit_bytes": state["HostConfig"]["Memory"],
            "export_failure_metrics": [
                row
                for row in failures
                if row["metric"].get("exporter") == "otlp_http/" + destination
            ],
            "producer": generated,
        }
    recovered = generate(stack, 3, "recovered-" + uuid4().hex[:8])
    tid, sid, _ = producer.identities(recovered["seed"], 1)
    wait_until(lambda: stack.query("tempo", "/api/traces/" + tid), 120)

    def recovered_log():
        response = stack.query(
            "loki",
            "/loki/api/v1/query_range?"
            + urlencode(
                {
                    "query": '{service_name="restaurantos-monitoring-synthetic"} | trace_id="'
                    + tid
                    + '"',
                    "limit": 10,
                }
            ),
        )
        return sid in json.dumps(response)

    wait_until(recovered_log, 120)
    report["fresh_export_after_recovery"] = True
    return report


def scraper(stack, seconds=180):
    wait_until(lambda: prom(stack, 'up{job="collector-self"}'))
    stack.compose("stop", "prometheus")
    stopped = time.monotonic()
    generate(stack, seconds, "scraper-gap")
    paused_seconds = time.monotonic() - stopped
    stack.compose("start", "prometheus")

    def gap():
        rows = prom(stack, 'up{job="collector-self"}[10m]')
        if not rows:
            return None
        stamps = [float(row[0]) for row in rows[0]["values"]]
        gaps = [b - a for a, b in pairwise(stamps)]
        return max(gaps) if gaps and max(gaps) > seconds - 5 else None

    observed = wait_until(gap, 120)
    return {
        "requested_fault_seconds": seconds,
        "observed_stopped_seconds": paused_seconds,
        "raw_scrape_sample_gap_seconds": observed,
        "missing_samples_not_backfilled": True,
    }


def saturation_config(stack):
    value = yaml.safe_load((ROOT / "monitoring/otel-collector.yaml").read_text())
    value["processors"]["batch"].update(send_batch_size=1, send_batch_max_size=1)
    for name in ("otlp_http/loki", "otlp_http/tempo"):
        value["exporters"][name]["sending_queue"]["queue_size"] = 1024
    path = stack.directory / "collector.yaml"
    path.write_text(yaml.safe_dump(value))
    (stack.directory / "override.yaml").write_text(
        yaml.safe_dump(
            {
                "services": {
                    "collector": {
                        "volumes": [
                            {
                                "type": "bind",
                                "source": str(path),
                                "target": "/etc/otelcol-contrib/config.yaml",
                                "read_only": True,
                                "bind": {"create_host_path": False},
                            }
                        ]
                    }
                }
            }
        )
    )


def saturation(stack):
    stack.compose("stop", "loki")
    generate(stack, 20, "saturation")
    failures = prom(stack, '{__name__=~"otelcol_exporter_enqueue_failed.*"}')
    assert any(
        float(row["value"][1]) > 0 and row["metric"].get("exporter") == "otlp_http/loki"
        for row in failures
    )
    state = json.loads(command("docker", "inspect", stack.container("collector")))[0]
    assert (
        state["State"]["Running"]
        and not state["State"]["OOMKilled"]
        and state["RestartCount"] == 0
    )
    stack.compose("start", "loki")
    wait_until(
        lambda: (
            stack.grafana("/api/datasources/uid/restaurantos-loki/health")["status"]
            == "OK"
        )
    )
    return {
        "reduced_queue_bytes": 1024,
        "records_per_batch": 1,
        "enqueue_failures_observed": True,
        "collector_survived": True,
        "production_queue_saturation_claimed": False,
        "collector_restarts": state["RestartCount"],
        "enqueue_failure_metrics": failures,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["host", "container"], default="host")
    parser.add_argument(
        "--scenario",
        choices=["smoke", "restart", "outage", "scraper", "saturation", "cleanup"],
        default="smoke",
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / "test-results/monitoring/result.json"
    )
    parser.add_argument("--fault-seconds", type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.fault_seconds <= 300:
        parser.error("fault duration must be 1..300 seconds")
    report = {
        "mode": args.mode,
        "scenario": args.scenario,
        "source_base": command("git", "rev-parse", "--short", "HEAD"),
        "configurations": {
            str(p.relative_to(ROOT)): "sha256:"
            + hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "monitoring").rglob("*.yaml")
        },
        "status": "failed",
        "cleanup_verified": False,
    }
    try:
        project = None
        try:
            with disposable_monitoring(args.mode) as stack:
                project = stack.project
                if args.scenario == "saturation":
                    saturation_config(stack)
                stack.up()
                if args.scenario == "cleanup":
                    raise InterruptedError("Intentional harness failure")
                report["results"] = {
                    "smoke": smoke,
                    "restart": restart,
                    "outage": lambda stack: outage(stack, args.fault_seconds),
                    "scraper": lambda stack: scraper(stack, args.fault_seconds),
                    "saturation": saturation,
                }[args.scenario](stack)
        finally:
            if project:
                report["cleanup_verified"] = all(
                    not command(
                        "docker",
                        kind,
                        "ls",
                        "-q",
                        "--filter",
                        "label=com.docker.compose.project=" + project,
                    )
                    for kind in ("container", "volume", "network")
                )
        report["status"] = "passed"
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "cleanup_verified": report["cleanup_verified"],
                    "report": str(args.report),
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
