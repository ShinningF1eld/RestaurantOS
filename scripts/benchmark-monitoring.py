"""Declared 2-minute warmup / 10-minute monitoring resource experiment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import threading
import time
from itertools import pairwise
from pathlib import Path
from uuid import uuid4

from test_support.monitoring_environment import ROOT, command, disposable_monitoring
from test_support.processes import stop_processes

spec = importlib.util.spec_from_file_location(
    "monitoring_check", ROOT / "scripts/check-monitoring.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def memory_bytes(value):
    matched = re.fullmatch(r"([\d.]+)\s*([a-zA-Z]+)", value)
    if not matched:
        raise ValueError("Invalid Docker memory measurement")
    number, unit = matched.groups()
    factors = {
        "B": 1,
        "kB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
    }
    return int(float(number) * factors[unit])


def disk(stack, image):
    output = {}
    for service, user in [
        ("prometheus", "65534"),
        ("grafana", "472"),
        ("loki", "10001"),
        ("tempo", "10001"),
    ]:
        name = stack.project + "-disk-" + service
        script = """import json
from pathlib import Path
logical=allocated=count=0
for p in Path('/data').rglob('*'):
 try:
  if p.is_file():
   s=p.stat();logical+=s.st_size;allocated+=s.st_blocks*512;count+=1
 except FileNotFoundError: pass
print(json.dumps({'logical_bytes':logical,'allocated_bytes':allocated,'files':count}))
"""
        try:
            output[service] = json.loads(
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
                    "--mount",
                    "type=volume,src="
                    + stack.project
                    + "_"
                    + service
                    + "_data,dst=/data,readonly",
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
    return {"observed_unix_seconds": time.time(), "volumes": output}


def service_for_id(mapping, identifier):
    matches = [
        name
        for key, name in mapping.items()
        if min(len(key), len(identifier)) >= 12
        and (key.startswith(identifier) or identifier.startswith(key))
    ]
    if len(matches) != 1:
        raise ValueError("Unrecognized or ambiguous stats container")
    return matches[0]


def stats_record(line):
    # Docker can emit cursor/clear sequences even when JSON output is piped.
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
    return json.loads(clean) if clean else None


class Stats:
    def __init__(self, stack, progress):
        self.samples = []
        self.errors = []
        self.progress = progress
        self.mapping = {
            stack.container(name): name
            for name in ("collector", "prometheus", "grafana", "loki", "tempo")
        }
        self.child = subprocess.Popen(
            ["docker", "stats", "--no-trunc", "--format", "{{json .}}", *self.mapping],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            for line in self.child.stdout:
                data = stats_record(line)
                if data is None:
                    continue
                service = service_for_id(self.mapping, data["ID"])
                self.samples.append(
                    {
                        "time": time.time(),
                        "service": service,
                        "memory_bytes": memory_bytes(data["MemUsage"].split(" / ")[0]),
                        "cpu_percent": float(data["CPUPerc"].rstrip("%")),
                        "raw_memory": data["MemUsage"],
                    }
                )
                if len(self.samples) % 25 == 0:
                    self.progress.write_text(
                        json.dumps(
                            {
                                "sample_count": len(self.samples),
                                "observed_unix_seconds": time.time(),
                            }
                        )
                        + "\n"
                    )
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.errors.append(type(error).__name__)

    def stop(self):
        stop_processes(self.child)
        self.thread.join(timeout=10)
        if self.thread.is_alive() or self.errors:
            raise RuntimeError("Stats collection failed")


def run(stack, report, progress):
    if not stack.state["ephemeral"]:
        raise ValueError("Benchmark requires disposable monitoring")
    image = checker.build_generator()
    report["generator_image_id"] = image
    report["observer_limits"] = {
        "volume_reader_memory_bytes": 128000000,
        "container_generator_memory_bytes": 128000000
        if stack.state["mode"] == "container"
        else None,
        "host_observer_memory_measured": False,
        "docker_memory_method": "Docker CLI cache-adjusted working set; rounded display converted to bytes",
        "cpu_units": "100 percent is one logical CPU; samples are not continuous maxima",
    }
    stack.compose("create")
    report["disk_before_startup"] = disk(stack, image)
    stack.up()
    plugins = command(
        "docker",
        "exec",
        stack.container("grafana"),
        "ls",
        "-1",
        "/var/lib/grafana/plugins",
    )
    if plugins:
        raise RuntimeError(
            "Unexpected Grafana startup plugins; image/config no longer fixes inputs"
        )
    report["grafana_automatic_plugins_present"] = False
    report["disk_after_startup"] = disk(stack, image)
    stats = Stats(stack, progress.with_name(progress.stem + "-samples.json"))
    seed = "benchmark-" + uuid4().hex[:8]
    args = [
        "--rate",
        "5",
        "--duration",
        "720",
        "--warmup",
        "120",
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
            "http://127.0.0.1:" + str(stack.port("collector", 4318)),
            *args,
        ]
    else:
        cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            stack.project + "_monitoring",
            "--read-only",
            "--memory",
            "128000000",
            "--memory-swap",
            "128000000",
            "--pids-limit",
            "64",
            image,
            "--endpoint",
            "http://collector:4318",
            *args,
        ]
    child = subprocess.Popen(
        cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    deadline = threading.Timer(810, child.terminate)
    deadline.daemon = True
    deadline.start()
    started = time.time()
    try:
        # The generator reports an explicit boundary before its final summary.
        for line in child.stdout:
            record = json.loads(line)
            if record.get("phase") == "warmup_complete":
                if stats.errors or not stats.samples:
                    raise RuntimeError("Resource observer failed during warmup")
                report["disk_after_warmup"] = disk(stack, image)
            else:
                report["producer"] = record
            progress.write_text(
                json.dumps(
                    {
                        "mode": stack.state["mode"],
                        "elapsed": time.time() - started,
                        "phase": record.get("phase", "producer_complete"),
                        "sample_count": len(stats.samples),
                    }
                )
                + "\n"
            )
        child.wait(timeout=30)
        deadline.cancel()
        if child.returncode or not report.get("producer", {}).get("complete"):
            raise RuntimeError("Declared benchmark workload did not complete")
        report["disk_after_measurement"] = disk(stack, image)
        report["reconciliation"] = checker.reconcile(stack, report["producer"])
        report["containers"] = checker.inspect_stack(stack)
        report["collector_failure_metrics"] = checker.prom(
            stack,
            '{__name__=~"otelcol_exporter_.*(failed|queue).*|otelcol_receiver_.*refused.*"}',
        )
        failed = [
            row
            for row in report["collector_failure_metrics"]
            if (
                "failed" in row["metric"]["__name__"]
                or "refused" in row["metric"]["__name__"]
            )
            and float(row["value"][1]) != 0
        ]
        if failed:
            raise RuntimeError("Healthy benchmark observed export/refusal failures")
    finally:
        deadline.cancel()
        report["samples"] = stats.samples
        try:
            stop_processes(child)
        finally:
            try:
                stats.stop()
            finally:
                if stack.state["mode"] == "container":
                    cleanup = subprocess.run(
                        ["docker", "rm", "-f", "-v", name],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                    )
                    if cleanup.returncode and "No such container" not in cleanup.stderr:
                        raise RuntimeError("Benchmark producer cleanup failed")
    source = report["producer"]
    lower = source["started_unix_seconds"] + 120
    upper = source["started_unix_seconds"] + 720
    selected = [sample for sample in stats.samples if lower <= sample["time"] < upper]
    summary = {}
    for service in ("collector", "prometheus", "grafana", "loki", "tempo"):
        rows = [r for r in selected if r["service"] == service]
        if not rows:
            raise RuntimeError("Missing resource samples")
        summary[service] = {
            "sample_count": len(rows),
            "peak_sampled_memory_bytes": max(r["memory_bytes"] for r in rows),
            "peak_sampled_cpu_percent": max(r["cpu_percent"] for r in rows),
            "mean_cpu_percent": sum(r["cpu_percent"] for r in rows) / len(rows),
            "maximum_sample_gap_seconds": max(
                (b["time"] - a["time"] for a, b in pairwise(rows)), default=0
            ),
        }
    groups = {}
    for sample in selected:
        groups.setdefault(int(sample["time"]), {})[sample["service"]] = sample
    complete = [v for v in groups.values() if len(v) == 5]
    if not complete:
        raise RuntimeError("No complete aggregate resource samples")
    report["resource_summary"] = {
        "services": summary,
        "complete_second_buckets": len(complete),
        "aggregate_peak_sampled_memory_bytes": max(
            sum(r["memory_bytes"] for r in group.values()) for group in complete
        ),
        "aggregate_peak_sampled_cpu_percent": max(
            sum(r["cpu_percent"] for r in group.values()) for group in complete
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["host", "container"], required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError(
            "Refusing to overwrite a retained run; choose a new report path"
        )
    active = command(
        "docker", "ps", "--format", '{{.Label "com.docker.compose.project"}}'
    ).splitlines()
    if any(project.startswith("restaurantos-monitoring-") for project in active):
        raise RuntimeError("Stop other monitoring stacks before resource acceptance")
    report = {
        "mode": args.mode,
        "status": "failed",
        "cleanup_verified": False,
        "engine": json.loads(command("docker", "info", "--format", "{{json .}}")),
    }
    # Keep only capacity/platform, not full engine inventory or registry settings.
    report["engine"] = {
        k: report["engine"][k]
        for k in ("Architecture", "NCPU", "MemTotal", "ServerVersion")
    }
    report["source_base"] = command("git", "rev-parse", "--short", "HEAD")
    report["background_container_count"] = len(
        command("docker", "ps", "-q").splitlines()
    )
    report["configuration_hashes"] = {
        str(path.relative_to(ROOT)): "sha256:"
        + hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [
            *(ROOT / "monitoring").rglob("*.yaml"),
            ROOT / "scripts/generate-monitoring-telemetry.py",
            Path(__file__).resolve(),
            ROOT / "scripts/check-monitoring.py",
            ROOT / "scripts/test_support/monitoring_environment.py",
            ROOT / "monitoring/images.lock.json",
        ]
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    project = None
    try:
        with disposable_monitoring(args.mode) as stack:
            project = stack.project
            run(stack, report, args.report.with_suffix(".progress.json"))
        report["status"] = "passed"
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
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
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(report["status"], flush=True)


if __name__ == "__main__":
    main()
