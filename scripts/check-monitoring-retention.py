"""Prove stored old fixtures are physically deleted in disposable monitoring."""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import runpy
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

import yaml
from test_support.monitoring_environment import (
    ROOT,
    command,
    disposable_monitoring,
    require_local_engine,
    wait_until,
)

spec = importlib.util.spec_from_file_location(
    "monitoring_checker", ROOT / "scripts/check-monitoring.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def merge(base, patch):
    for key, value in patch.items():
        if isinstance(value, dict):
            merge(base.setdefault(key, {}), value)
        else:
            base[key] = value


def files(stack, service, image):
    if not stack.state["ephemeral"]:
        raise ValueError("Retention requires disposable storage")
    volume = stack.project + "_" + service + "_data"
    user = "65534:65534" if service == "prometheus" else "10001:10001"
    script = """import json
from pathlib import Path
files={}; metadata={}
for p in Path('/data').rglob('*'):
 try:
  if p.is_file():
   name=str(p.relative_to('/data')); files[name]=p.stat().st_size
   if p.name=='meta.json': metadata[name]=json.loads(p.read_text())
 except (FileNotFoundError, ValueError): pass
print(json.dumps({'files':files,'metadata':metadata}))
"""
    name = stack.project + "-inspect-" + uuid4().hex[:6]
    try:
        return json.loads(
            command(
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--network",
                "none",
                "--read-only",
                "--user",
                user,
                "--memory",
                "128000000",
                "--cap-drop",
                "ALL",
                "--mount",
                f"type=volume,src={volume},dst=/data,readonly",
                "--entrypoint",
                "python",
                image,
                "-c",
                script,
                timeout=30,
            )
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", "-v", name],
            capture_output=True,
            check=False,
            timeout=30,
        )


def post(stack, signal, records, *, service=None):
    payload = checker.producer.payload(signal, records)
    if service is not None:
        assert signal == "traces"
        payload["resourceSpans"][0]["resource"]["attributes"][0]["value"] = {
            "stringValue": service
        }
    body = json.dumps(payload).encode()
    request = Request(
        f"http://127.0.0.1:{stack.port('collector', 4318)}/v1/" + signal,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
        assert not json.load(response).get("partialSuccess")


def verify_recent_worker_link(stack, old_trace_id, old_span_id):
    """A current retry remains discoverable after its origin is physically removed."""
    dashboards = runpy.run_path(str(ROOT / "scripts/check-operator-dashboards.py"))
    model = stack.grafana("/api/dashboards/uid/restaurantos-background")["dashboard"]
    panel = next(
        panel
        for panel in model["panels"]
        if panel["title"] == "Scheduled retries and failed attempts"
    )
    now = time.time_ns()
    span, _ = checker.producer.operation("retention-worker-retry", 1, now)
    attempt = span[0]
    attempt.update(
        name="consumer attempt",
        kind=5,
        links=[{"traceId": old_trace_id, "spanId": old_span_id}],
        attributes=[
            {"key": key, "value": {"stringValue": value}}
            for key, value in (
                ("consumer", "analytics"),
                ("outcome", "consumer_retry_scheduled"),
            )
        ],
    )
    post(stack, "traces", [attempt], service="restaurantos-worker")
    start = (now // 10**9) - 5

    def visible_attempt():
        end = int(time.time()) + 1
        search = dashboards["linked_query"](
            panel,
            start * 1000,
            end * 1000,
            consumer="analytics",
            outcome="consumer_retry_scheduled",
        )
        matches = dashboards["query"](
            stack,
            "tempo",
            "/api/search",
            q=search["expr"],
            start=start,
            end=end,
        ).get("traces", [])
        return any(row["traceID"] == attempt["traceId"] for row in matches)

    wait_until(visible_attempt, 60)
    (stored,) = checker.trace_spans(
        stack.query("tempo", "/api/traces/" + attempt["traceId"])
    )
    (link,) = stored["links"]
    assert checker.hex_id(link["traceId"]) == old_trace_id
    assert checker.hex_id(link["spanId"]) == old_span_id
    assert not stored.get("parentSpanId")


def run(stack, report, *, dashboard_links=False):
    if not stack.state["ephemeral"] or not stack.project.startswith(
        "restaurantos-monitoring-test-"
    ):
        raise ValueError("Retention requires an owned disposable project")
    require_local_engine()
    image = checker.build_generator()
    accelerated = yaml.safe_load(
        (ROOT / "monitoring/testing/retention.yaml").read_text()
    )
    configs = {}
    for service in ("loki", "tempo"):
        value = yaml.safe_load((ROOT / "monitoring" / (service + ".yaml")).read_text())
        merge(value, accelerated[service])
        if service == "loki":
            value["compactor"]["retention_enabled"] = False
        else:
            value["compactor"]["disabled"] = True
        configs[service] = value
    override = {"services": {}}
    for service, value in configs.items():
        path = stack.directory / (service + ".yaml")
        path.write_text(yaml.safe_dump(value))
        override["services"][service] = {
            "volumes": [
                {
                    "type": "bind",
                    "source": str(path),
                    "target": "/etc/" + service + "/config.yaml",
                    "read_only": True,
                    "bind": {"create_host_path": False},
                }
            ]
        }
    (stack.directory / "override.yaml").write_text(yaml.safe_dump(override))
    stack.compose("create")
    now = time.time()
    fixture = stack.directory / "fixtures.txt"
    fixture.write_text(
        "# TYPE monitoring_retention_control gauge\n"
        + f'monitoring_retention_control{{age="old"}} 1 {now - 8 * 86400}\n'
        + f'monitoring_retention_control{{age="recent"}} 2 {now - 3600}\n# EOF\n',
        newline="\n",
    )
    stack.compose(
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "/bin/promtool",
        "-v",
        str(fixture) + ":/fixture.txt:ro",
        "prometheus",
        "tsdb",
        "create-blocks-from",
        "openmetrics",
        "/fixture.txt",
        "/prometheus",
    )
    primed = files(stack, "prometheus", image)
    old_blocks = {
        name.split("/")[0]
        for name, meta in primed["metadata"].items()
        if meta["maxTime"] < (now - 7 * 86400) * 1000
    }
    recent_blocks = {
        name.split("/")[0]
        for name, meta in primed["metadata"].items()
        if meta["minTime"] > (now - 7 * 86400) * 1000
    }
    assert old_blocks and recent_blocks
    report["prometheus_old_and_control_blocks_stored_before_start"] = True
    stack.up()
    checker.wait_until(
        lambda: checker.prom(stack, 'monitoring_retention_control{age="recent"}[2h]')
    )

    def prom_deleted():
        snapshot = files(stack, "prometheus", image)
        return not any(name.split("/")[0] in old_blocks for name in snapshot["files"])

    wait_until(prom_deleted, 180)
    assert any(
        name.split("/")[0] in recent_blocks
        for name in files(stack, "prometheus", image)["files"]
    )
    report["prometheus_old_blocks_physically_deleted_control_retained"] = True
    old_ns, fresh_ns = int((now - 4 * 86400) * 1e9), time.time_ns()
    old_spans, old_log = checker.producer.operation("retention-old", 1, old_ns)
    post(stack, "traces", old_spans)
    post(stack, "logs", [old_log])
    tid, old_span_id, _ = checker.producer.identities("retention-old", 1)
    wait_until(lambda: stack.query("tempo", "/api/traces/" + tid))
    query = '{service_name="restaurantos-monitoring-synthetic"}'

    def old_log_query():
        return stack.query(
            "loki",
            "/loki/api/v1/query_range?"
            + urlencode(
                {
                    "query": query,
                    "start": old_ns - 1_000_000_000,
                    "end": old_ns + 1_000_000_000,
                }
            ),
        )["data"]["result"]

    wait_until(old_log_query)
    report["old_trace_and_log_queryable_before_cleanup"] = True

    def old_tempo_blocks():
        snapshot = files(stack, "tempo", image)
        blocks = []
        for name, meta in snapshot["metadata"].items():
            if name.startswith("blocks/") and "endTime" in meta:
                end = datetime.datetime.fromisoformat(meta["endTime"]).timestamp()
                if end < now - 3 * 86400:
                    blocks.append(name.rsplit("/", 1)[0])
        return blocks

    expired_trace_paths = wait_until(old_tempo_blocks, 180)
    # Separate the recent control into a new block/head.
    fresh_ns = time.time_ns()
    fresh_spans, fresh_log = checker.producer.operation("retention-fresh", 1, fresh_ns)
    post(stack, "traces", fresh_spans)
    post(stack, "logs", [fresh_log])
    fresh_tid, _, _ = checker.producer.identities("retention-fresh", 1)
    wait_until(lambda: stack.query("tempo", "/api/traces/" + fresh_tid))
    # Force log flush and clean shutdown to ship TSDB heads before retention.
    command(
        "docker",
        "exec",
        stack.container("prometheus"),
        "/bin/wget",
        "-q",
        "-O",
        "-",
        "--post-data=",
        "http://loki:3100/flush",
    )

    def loki_metric(name):
        body = stack.internal("http://loki:3100/metrics")
        for line in body.splitlines():
            if line.startswith(name + " "):
                return float(line.split()[1])
        raise RuntimeError("Missing Loki checkpoint/flush metric")

    wait_until(lambda: loki_metric("loki_ingester_memory_chunks") == 0, 120)

    def completed_checkpoints():
        return {
            "/".join(name.split("/")[:2])
            for name in files(stack, "loki", image)["files"]
            if name.startswith("wal/checkpoint.") and ".tmp" not in name.split("/")[1]
        }

    checkpoint = completed_checkpoints()
    wait_until(lambda: completed_checkpoints() - checkpoint, 120)
    assert loki_metric("loki_ingester_checkpoint_creations_failed_total") == 0
    report["loki_flushed_chunks_and_subsequent_checkpoint_verified"] = True
    stack.compose("stop", "loki")
    loki_before = files(stack, "loki", image)
    chunk_paths = {
        name for name in loki_before["files"] if name.startswith("chunks/fake/")
    }
    assert len(chunk_paths) == 2, (
        "Exactly one old and one fresh log chunk must be stored"
    )
    report["old_log_chunks_stored_count"] = len(chunk_paths)
    configs["loki"]["compactor"]["retention_enabled"] = True
    configs["tempo"]["compactor"]["disabled"] = False
    for service, value in configs.items():
        (stack.directory / (service + ".yaml")).write_text(yaml.safe_dump(value))
    stack.compose("up", "-d", "loki")
    stack.compose("restart", "tempo")
    wait_until(lambda: stack.internal("http://loki:3100/ready"))
    wait_until(lambda: stack.internal("http://tempo:3200/ready"))

    def tempo_deleted():
        snapshot = files(stack, "tempo", image)
        return not any(
            any(name.startswith(path + "/") for path in expired_trace_paths)
            for name in snapshot["files"]
        )

    wait_until(tempo_deleted, 600)

    def trace_absent():
        try:
            stack.query("tempo", "/api/traces/" + tid)
        except HTTPError as error:
            return error.code == 404
        return False

    wait_until(trace_absent, 180)
    assert stack.query("tempo", "/api/traces/" + fresh_tid)
    report["tempo_old_block_files_deleted_old_trace_absent_recent_trace_present"] = True
    if dashboard_links:
        verify_recent_worker_link(stack, tid, old_span_id)
        report["dashboard_retry_search_resolves_worker_attempt_with_expired_origin"] = (
            True
        )

    def loki_deleted():
        after = files(stack, "loki", image)
        return len(chunk_paths - set(after["files"])) >= 1 and not old_log_query()

    wait_until(loki_deleted, 900)
    recent = stack.query(
        "loki",
        "/loki/api/v1/query_range?"
        + urlencode(
            {
                "query": query,
                "start": fresh_ns - 1_000_000_000,
                "end": fresh_ns + 1_000_000_000,
            }
        ),
    )["data"]["result"]
    assert recent
    report["loki_old_chunk_files_deleted_old_log_absent_recent_log_present"] = True
    report["retention_durations_preserved"] = {
        "prometheus": "7d",
        "loki": "72h",
        "tempo": "72h",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, default=ROOT / "test-results/monitoring/retention.json"
    )
    parser.add_argument("--dashboard-links", action="store_true")
    args = parser.parse_args()
    report = {"status": "failed", "cleanup_verified": False}
    project = None
    try:
        with disposable_monitoring("host") as stack:
            project = stack.project
            run(stack, report, dashboard_links=args.dashboard_links)
        report["status"] = "passed"
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        report["cleanup_verified"] = project is not None and all(
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
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
