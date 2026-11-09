"""Verify provisioned operator dashboards against the pinned monitoring stack."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import yaml
from test_support.dashboard_fixtures import activity, edge_cases, labels
from test_support.monitoring_environment import (
    ROOT,
    disposable_monitoring,
    require_local_engine,
    wait_until,
)

PROVISIONING = ROOT / "monitoring/grafana/provisioning"
DASHBOARDS = {
    "restaurantos-service": "Service Overview",
    "restaurantos-database-redis": "Database & Redis",
    "restaurantos-background": "Background Processing",
    "restaurantos-business": "Business Activity",
}
DATASOURCES = {"restaurantos-" + name: name for name in ("prometheus", "loki", "tempo")}
VARIABLE = re.compile(r"\$\{([^}]+)\}")


def dashboard_models():
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((PROVISIONING / "dashboards/definitions").glob("*.json"))
    }


def linked_query(panel, start_ms, end_ms, **fields):
    url = panel["fieldConfig"]["defaults"]["links"][0]["url"]
    return explore_query(url, start_ms, end_ms, fields)


def explore_query(url, start_ms, end_ms, fields):
    values = {"__from": start_ms, "__to": end_ms}
    values.update(
        {f"__field.labels.{key}:percentencode": value for key, value in fields.items()}
    )
    rendered = VARIABLE.sub(lambda match: quote(str(values[match[1]]), safe=""), url)
    parts = urlsplit(rendered)
    assert (parts.scheme, parts.netloc, parts.path) == ("", "", "/explore")
    params = parse_qs(parts.query, strict_parsing=True)
    assert set(params) == {"schemaVersion", "panes"} and params["schemaVersion"] == [
        "1"
    ]
    (pane,) = json.loads(params["panes"][0]).values()
    assert pane["range"] == {"from": str(start_ms), "to": str(end_ms)}
    (query,) = pane["queries"]
    assert query["datasource"] == {
        "uid": pane["datasource"],
        "type": DATASOURCES[pane["datasource"]],
    }
    return query


def check_models(models):
    assert {uid: model["title"] for uid, model in models.items()} == DASHBOARDS
    sources = yaml.safe_load(
        (PROVISIONING / "datasources/datasources.yaml").read_text()
    )
    assert {
        source["uid"]: source["type"] for source in sources["datasources"]
    } == DATASOURCES
    panels = {}
    link_count = 0
    for uid, model in models.items():
        assert model["uid"] == uid and not model["editable"]
        assert len({panel["id"] for panel in model["panels"]}) == len(model["panels"])
        assert model["links"][0]["keepTime"]
        for panel in model["panels"]:
            if "targets" not in panel:
                continue
            assert panel["title"] not in panels
            panels[panel["title"]] = panel
            for target in panel["targets"]:
                assert (
                    target["datasource"]
                    == panel["datasource"]
                    == {"uid": "restaurantos-prometheus", "type": "prometheus"}
                )
                assert target["instant"] != target["range"]
                assert "vector(0)" not in target["expr"]
                assert not re.search(
                    r"\b(tenant_id|organization_id|restaurant_id|user_id|customer_id|order_id|event_id|delivery_id|trace_id)\b",
                    target["expr"],
                )
            for link in panel["fieldConfig"]["defaults"].get("links", []):
                query = explore_query(
                    link["url"],
                    1_000,
                    10_000,
                    {
                        "http_route": "/api/orders/{order_id}",
                        "outcome": "server_error",
                        "consumer": "analytics",
                    },
                )
                expression = query["expr"].replace("/api/orders/{order_id}", "")
                assert not re.search(
                    r"\b(trace_id|order_id|event_id|delivery_id)\b", expression
                )
                link_count += 1
    return panels, link_count


def fixture_rules(panels):
    active = activity()
    actual = {
        (title, target["refId"])
        for title, panel in panels.items()
        for target in panel["targets"]
    }
    assert set(active.checks) == actual, (
        f"Fixture/target mismatch: {set(active.checks) ^ actual}"
    )
    scenarios = []
    results = {}
    for scenario in [active, *edge_cases()]:
        checks = []
        results[scenario.name] = {}
        for (title, ref), (unit, samples) in scenario.checks.items():
            panel = panels[title]
            assert panel["fieldConfig"]["defaults"]["unit"] == unit, title
            (target,) = (
                target for target in panel["targets"] if target["refId"] == ref
            )
            expected = [
                {"labels": labels(dimensions), "value": number}
                for number, dimensions in samples
            ]
            checks.append(
                {
                    "expr": target["expr"],
                    "eval_time": scenario.evaluation,
                    "exp_samples": expected,
                }
            )
            results[scenario.name][f"{title} ({ref})"] = {
                "unit": unit,
                "samples": expected,
            }
        scenarios.append(
            {
                "name": scenario.name,
                "interval": "10s",
                "input_series": scenario.series,
                "promql_expr_test": checks,
            }
        )
    return {
        "evaluation_interval": "10s",
        "fuzzy_compare": True,
        "tests": scenarios,
    }, results


def promtool(panels):
    require_local_engine()
    rules, results = fixture_rules(panels)
    lock = json.loads((ROOT / "monitoring/images.lock.json").read_text())
    image = lock["images"]["prometheus"]["reference"]
    with tempfile.TemporaryDirectory(
        prefix="restaurantos-dashboard-fixtures-"
    ) as folder:
        path = Path(folder) / "queries.yaml"
        path.write_text(yaml.safe_dump(rules), encoding="utf-8")
        path.chmod(0o444)
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "300000000",
                "--memory-swap",
                "300000000",
                "--pids-limit",
                "128",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=16m",
                "--mount",
                f"type=bind,src={path},dst=/queries.yaml,readonly",
                "--entrypoint",
                "/bin/promtool",
                image,
                "test",
                "rules",
                "/queries.yaml",
            ],
            check=True,
            timeout=120,
        )
    print(
        f"PASS: {sum(map(len, results.values()))} exact PromQL fixture checks",
        flush=True,
    )
    return results


def query(stack, store, path, **params):
    return stack.query(store, path + "?" + urlencode(params))


def instant(stack, expression):
    response = query(stack, "prometheus", "/api/v1/query", query=expression)
    assert response["status"] == "success", expression
    return response["data"]["result"]


def verify_provisioned(stack, models):
    dashboard_list = stack.grafana("/api/search?type=dash-db")
    assert {result["uid"] for result in dashboard_list} == set(models)
    for uid, model in models.items():
        stored = stack.grafana("/api/dashboards/uid/" + uid)
        assert (
            stored["meta"]["provisioned"]
            and stored["meta"]["folderUid"] == "restaurantos-operator"
        )
        assert stored["dashboard"]["title"] == model["title"]
        by_id = {panel["id"]: panel for panel in stored["dashboard"]["panels"]}
        for panel in model["panels"]:
            actual = by_id[panel["id"]]
            assert actual["title"] == panel["title"]
            if "targets" in panel:
                assert actual["targets"] == panel["targets"]
                assert actual["fieldConfig"] == panel["fieldConfig"]
    assert {
        source["uid"]: source["type"] for source in stack.grafana("/api/datasources")
    } == DATASOURCES


def seed_prometheus(stack):
    """Import only the known active fixture into the owned Prometheus volume."""
    if not stack.state["ephemeral"]:
        raise ValueError("Dashboard fixtures require disposable monitoring storage")
    stack.compose("create")
    start = int(time.time()) - 3600
    timestamps = {
        "restaurantos_http_last_observation_seconds",
        "restaurantos_worker_collected_seconds",
        "restaurantos_business_collection_last_success_seconds",
    }
    fixture = stack.directory / "dashboard-fixture.txt"
    with fixture.open("w", encoding="utf-8", newline="\n") as output:
        for row in activity().series:
            offset = 0
            metric = row["series"].split("{", 1)[0]
            for token in row["values"].split():
                pattern, _, repeats = token.partition("x")
                initial, _, step = pattern.partition("+")
                for index in range(int(repeats or 0) + 1):
                    value = float(initial) + index * float(step or 0)
                    if metric in timestamps:
                        value += start
                    output.write(f"{row['series']} {value} {start + offset}\n")
                    offset += 10
        output.write("# EOF\n")
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
    return start + 120


def verify_api_samples(stack, panels, evaluation):
    evidence = {}
    for (title, ref), (unit, samples) in activity().checks.items():
        panel = panels[title]
        (target,) = (item for item in panel["targets"] if item["refId"] == ref)
        result = query(
            stack, "prometheus", "/api/v1/query", query=target["expr"], time=evaluation
        )
        assert result["status"] == "success", title
        actual = {
            tuple(sorted(row["metric"].items())): float(row["value"][1])
            for row in result["data"]["result"]
        }
        expected = {tuple(sorted(dims.items())): value for value, dims in samples}
        assert actual.keys() == expected.keys(), (title, ref, actual, expected)
        assert all(
            math.isclose(actual[key], value, abs_tol=1e-12)
            for key, value in expected.items()
        ), (
            title,
            ref,
            actual,
            expected,
        )
        evidence[f"{title} ({ref})"] = {
            "unit": unit,
            "samples": [
                {"labels": dict(dims), "value": value} for dims, value in actual.items()
            ],
        }
    return evidence


def send_business_freshness_fixture(stack):
    now = time.time_ns()
    values = {
        "collection.freshness_budget": 615,
        "collection.last_success": now / 1e9 - 90,
        "collection.success": 1,
        "sales.retained_orders_7d": 4,
    }
    metrics = [
        {
            "name": f"restaurantos.business.{name}",
            "gauge": {"dataPoints": [{"timeUnixNano": str(now), "asDouble": value}]},
        }
        for name, value in values.items()
    ]
    payload = {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "restaurantos-api"},
                        }
                    ]
                },
                "scopeMetrics": [{"metrics": metrics}],
            }
        ]
    }
    request = Request(
        f"http://127.0.0.1:{stack.port('collector', 4318)}/v1/metrics",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
        assert not json.load(response).get("partialSuccess")


def live_checks(models, panels):
    with disposable_monitoring() as stack:
        stack.up()
        verify_provisioned(stack, models)
        try:
            stack.grafana(
                "/api/dashboards/uid/restaurantos-service", authenticated=False
            )
        except HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("Anonymous dashboard access was accepted")

        def panel_data(title, ref=0):
            return instant(stack, panels[title]["targets"][ref]["expr"])

        assert panel_data("API requests") == []
        assert panel_data("Retained completed sales · seven UTC creation dates") == []
        wait_until(
            lambda: any(
                row["metric"]["job"] == "collector-telemetry" and row["value"][1] == "1"
                for row in panel_data("Prometheus scrape targets")
            ),
            timeout=30,
        )
        assert panel_data("API observation series")[0]["value"][1] == "0"
        send_business_freshness_fixture(stack)
        business_samples = {}
        for title, ref, expected in (
            ("Business snapshot collection", 0, "1"),
            ("Last successful business source collection age", 1, "615"),
            ("Retained completed orders · seven UTC creation dates", 0, "4"),
        ):
            rows = wait_until(
                lambda title=title, ref=ref: panel_data(title, ref), timeout=20
            )
            assert len(rows) == 1 and rows[0]["value"][1] == expected, title
            business_samples[title] = float(rows[0]["value"][1])
        for service in ("collector", "loki", "tempo"):
            stack.compose("stop", service)
            job = "collector-telemetry" if service == "collector" else service
            wait_until(
                lambda job=job: any(
                    row["metric"]["job"] == job and row["value"][1] == "0"
                    for row in panel_data("Prometheus scrape targets")
                ),
                timeout=30,
            )
            stack.compose("start", service)

        stack.compose("stop", "prometheus")

        def prometheus_unavailable():
            try:
                panel_data("Prometheus scrape targets")
            except HTTPError as error:
                return 400 <= error.code < 600
            return False

        wait_until(prometheus_unavailable, timeout=30)
        stack.down()
        evaluation = seed_prometheus(stack)
        stack.up()
        verify_provisioned(stack, models)
        samples = verify_api_samples(stack, panels, evaluation)
    print(
        f"PASS: clean provisioning, authentication, source outages, normal restart, {len(samples)} authenticated query results and cleanup",
        flush=True,
    )
    return {
        "provisioned": list(models),
        "authenticated_only": True,
        "source_outages": ["collector", "loki", "tempo", "prometheus"],
        "restart": True,
        "api_samples": samples,
        "business_freshness_otlp_samples": business_samples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="start an owned five-service monitoring stack",
    )
    parser.add_argument(
        "--report", type=Path, help="write sanitized synthetic query evidence"
    )
    args = parser.parse_args()
    models = dashboard_models()
    panels, link_count = check_models(models)
    print(
        f"PASS: {len(models)} dashboard models, {len(panels)} query panels, {link_count} Explore links",
        flush=True,
    )
    evidence = {"fixtures": promtool(panels)}
    if args.runtime:
        evidence["runtime"] = live_checks(models, panels)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
