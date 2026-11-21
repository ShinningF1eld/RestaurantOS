"""Check the shipped alert expressions with the pinned Prometheus rule engine."""

import json
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import yaml
from test_support.monitoring_environment import ROOT, command, require_local_engine

MONITORING = ROOT / "monitoring"


def series(name, values, *, service="", **labels):
    labels = {"job": "collector-telemetry", "instance": "collector:8889", **labels}
    if service:
        labels["service_name"] = "restaurantos-" + service
    dimensions = ",".join(f'{key}="{value}"' for key, value in labels.items())
    return {"series": f"{name}{{{dimensions}}}", "values": values}


def expect(expression, value=None, **labels):
    dimensions = ",".join(f'{key}="{val}"' for key, val in labels.items())
    return {
        "expr": expression,
        "eval_time": "5m",
        "exp_samples": []
        if value is None
        else [{"labels": "{" + dimensions + "}", "value": value}],
    }


def cases():
    reports = yaml.safe_load(
        (MONITORING / "grafana/provisioning/alerting/local-incidents.yaml").read_text(
            encoding="utf-8"
        )
    )["groups"][0]["rules"]
    queries = {
        row["uid"].removeprefix("ros-local-"): row["data"][0]["model"]["expr"]
        for row in reports
    }
    results = []

    def add(inputs, checks):
        results.append(
            {"interval": "5s", "input_series": inputs, "promql_expr_test": checks}
        )

    scrape = series("up", "1+0x60")
    fresh_api = series(
        "restaurantos_http_last_observation_seconds", "0+5x60", service="api"
    )
    fresh_delivery = series(
        "restaurantos_delivery_collected_seconds", "0+5x60", service="api"
    )
    fresh_worker = series(
        "restaurantos_worker_collected_seconds", "0+5x60", service="worker"
    )
    eligible = "restaurantos_http_eligible_requests_total"
    fail = series(eligible, "0+1x60", service="api", outcome="server_error")
    success = series(eligible, "0+4x60", service="api", outcome="success")
    add([scrape, fresh_api, success, fail], [expect(queries["api"], 2, signal="api")])
    zero = series(eligible, "0+0x60", service="api", outcome="server_error")
    add([scrape, fresh_api, success, zero], [expect(queries["api"], 0, signal="api")])
    add([scrape, fresh_api, zero], [expect(queries["api"], 1, signal="api")])
    add(
        [
            scrape,
            fresh_api,
            success,
            series(eligible, "0+0x54 1+1x5", service="api", outcome="server_error"),
        ],
        [expect(queries["api"], 1, signal="api")],
    )
    add([scrape, success, fail], [expect(queries["api"], 1, signal="api")])

    role = {"role": "api"}
    gauges = [
        series(f"restaurantos_pool_{gauge}", values, service="api", **role)
        for gauge, values in (("used", "0+0x60"), ("limit", "2+0x60"))
    ]
    timeouts = series(
        "restaurantos_pool_acquire_failures_total",
        "0+0x47 1+0x12",
        service="api",
        outcome="timeout",
        **role,
    )
    add(
        [scrape, *gauges, timeouts],
        [expect('sum(ros_alert:phase{signal="pool"})', 2)],
    )
    add(
        [
            scrape,
            *gauges,
            series(
                "restaurantos_pool_acquire_failures_total",
                "0+0x60",
                service="api",
                outcome="timeout",
                **role,
            ),
        ],
        [expect('sum(ros_alert:phase{signal="pool"})', 0)],
    )
    add(
        [series("up", "1+0x48 0+0x11"), *gauges, timeouts],
        [expect('sum(ros_alert:phase{signal="pool"})')],
    )
    saturated = [
        series(
            "restaurantos_pool_used",
            "8+0x60",
            service="worker",
            role="worker",
            worker_slot="0",
        ),
        series(
            "restaurantos_pool_limit",
            "10+0x60",
            service="worker",
            role="worker",
            worker_slot="0",
        ),
    ]
    for progression, expected in (("0+0x60", 1), ("0+1x60", 2)):
        acquisitions = series(
            "restaurantos_pool_acquire_duration_seconds_count",
            progression,
            service="worker",
            role="worker",
            worker_slot="0",
            outcome="success",
        )
        add(
            [scrape, *saturated, acquisitions],
            [
                expect(
                    'sum(ros_alert:phase{signal="pool",role="worker",worker_slot="0"})',
                    expected,
                )
            ],
        )

    consumer = {"consumer": "analytics"}
    pending = series(
        "restaurantos_delivery_depth",
        "1+0x60",
        service="api",
        state="recovery_due",
        **consumer,
    )
    age = series(
        "restaurantos_delivery_oldest_seconds",
        "0+5x60",
        service="api",
        state="recovery_due",
        **consumer,
    )
    terminal = series(
        "restaurantos_delivery_depth",
        "1+0x60",
        service="api",
        state="terminal",
        **consumer,
    )
    add(
        [scrape, fresh_delivery, pending, age],
        [
            expect('sum(ros_alert:phase{signal="backlog",consumer="analytics"})', 2),
            expect(
                f"sum(({queries['backlog']}) and on (consumer) restaurantos_delivery_depth)",
                2,
            ),
        ],
    )
    add(
        [scrape, fresh_delivery, terminal],
        [expect('sum(ros_alert:phase{signal="jobs",consumer="analytics"})', 2)],
    )
    retry = "restaurantos_worker_retries_total"
    clean = series(
        "restaurantos_delivery_depth",
        "0+0x60",
        service="api",
        state="terminal",
        **consumer,
    )
    add(
        [
            scrape,
            fresh_delivery,
            fresh_worker,
            clean,
            series(
                retry,
                "0+0x48 1 2 0 1+0x8",
                service="worker",
                worker_slot="0",
                **consumer,
            ),
        ],
        [
            expect('sum(ros_alert:retries_5m{consumer="analytics"} >= bool 3)', 1),
            expect('sum(ros_alert:phase{signal="jobs",consumer="analytics"})', 2),
        ],
    )
    add(
        [
            scrape,
            fresh_delivery,
            fresh_worker,
            clean,
            series(
                retry, "0+0x48 1+0x11", service="worker", worker_slot="0", **consumer
            ),
        ],
        [
            expect('sum(ros_alert:retries_5m{consumer="analytics"} >= bool 1)', 1),
            expect('sum(ros_alert:phase{signal="jobs",consumer="analytics"})', 0),
        ],
    )
    add(
        [scrape, fresh_delivery, clean],
        [expect('sum(ros_alert:phase{signal="jobs",consumer="analytics"})')],
    )
    return {
        "rule_files": ["/alert-signals.yaml"],
        "evaluation_interval": "15s",
        "tests": results,
    }


def main():
    require_local_engine()
    lock = json.loads((MONITORING / "images.lock.json").read_text())
    image = lock["images"]["prometheus"]["reference"]
    with tempfile.TemporaryDirectory(prefix="restaurantos-incident-rules-") as folder:
        tests = Path(folder) / "tests.yaml"
        tests.write_text(yaml.safe_dump(cases()), encoding="utf-8")
        name = "restaurantos-incident-rules-" + uuid4().hex
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--network",
                    "none",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=32m",
                    "--cap-drop",
                    "ALL",
                    "--memory",
                    "200m",
                    "--pids-limit",
                    "64",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--mount",
                    f"type=bind,src={tests},dst=/tests.yaml,readonly",
                    "--mount",
                    f"type=bind,src={MONITORING / 'alert-signals.yaml'},dst=/alert-signals.yaml,readonly",
                    "--entrypoint",
                    "/bin/promtool",
                    image,
                    "test",
                    "rules",
                    "/tests.yaml",
                ],
                timeout=120,
                check=True,
            )
        finally:
            if command("docker", "ps", "-aq", "--filter", "name=^/" + name + "$"):
                command("docker", "rm", "--force", name)


if __name__ == "__main__":
    main()
