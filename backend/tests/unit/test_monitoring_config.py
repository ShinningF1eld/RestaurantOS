"""Critical telemetry bounds must not silently disappear from configuration."""

import importlib.util
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def config(name):
    return yaml.safe_load((ROOT / "monitoring" / name).read_text())


def test_collector_limits_apply_before_buffering_and_export():
    collector = config("otel-collector.yaml")
    receiver = collector["receivers"]["otlp"]["protocols"]
    assert set(receiver) == {"http"}
    assert 0 < receiver["http"]["max_request_body_size"] <= 65536
    assert receiver["http"]["include_metadata"] is False
    limiter = collector["processors"]["memory_limiter"]
    compose = config("compose.yaml")
    assert 0 < limiter["spike_limit_mib"] < limiter["limit_mib"]
    assert (
        limiter["limit_mib"] * 1024**2 < compose["services"]["collector"]["mem_limit"]
    )
    batch = collector["processors"]["batch"]
    assert 0 < batch["send_batch_size"] <= batch["send_batch_max_size"] <= 128
    assert batch["metadata_keys"] == []
    for name, pipeline in collector["service"]["pipelines"].items():
        assert pipeline["processors"][0] == "memory_limiter"
        policy = name.split("/", 1)[1] if "/" in name else "synthetic"
        assert policy in {"api", "frontend", "synthetic", "diagnostics"}
        assert pipeline["processors"].index("transform/" + policy) < pipeline[
            "processors"
        ].index("batch")
    for name in ("otlp_http/loki", "otlp_http/tempo"):
        exporter = collector["exporters"][name]
        queue = exporter["sending_queue"]
        assert queue["enabled"] and queue["sizer"] == "bytes"
        assert 0 < queue["queue_size"] <= 4 * 1024**2
        assert 0 < queue["num_consumers"] <= 2
        assert queue["block_on_overflow"] is False
        assert queue["wait_for_result"] is False
        assert "storage" not in queue
        assert exporter["timeout"] == "2s"
        assert exporter["retry_on_failure"]["max_elapsed_time"] == "10s"
    assert set(collector["exporters"]) == {
        "prometheus",
        "otlp_http/loki",
        "otlp_http/tempo",
    }


def test_frontend_policy_is_trace_only_with_independent_privacy_filtering():
    collector = config("otel-collector.yaml")
    pipelines = collector["service"]["pipelines"]
    assert set(pipelines) == {
        "metrics",
        "logs",
        "traces",
        "metrics/api",
        "metrics/diagnostics",
        "logs/api",
        "traces/api",
        "traces/frontend",
    }
    assert pipelines["traces/frontend"]["processors"] == [
        "memory_limiter",
        "filter/frontend",
        "transform/frontend",
        "batch",
    ]
    conditions = collector["processors"]["filter/frontend"]["trace_conditions"]
    assert conditions[0]["conditions"] == [
        'resource.attributes["service.name"] != "restaurantos-frontend"'
    ]
    assert conditions[-1] == {"context": "spanevent", "conditions": ["true"]}
    statements = collector["processors"]["transform/frontend"]["trace_statements"]
    assert 'keep_keys(span.attributes, ["http.route"])' in statements
    assert 'set(span.status.message, "")' in statements
    assert 'set(span.trace_state, "")' in statements
    assert 'keep_keys(resource.attributes, ["service.name"])' in statements
    assert any(
        '"<unmatched>"' in statement and "IsMatch" in statement
        for statement in statements
    )


def test_workload_metrics_expire_and_self_metrics_have_a_separate_scrape():
    collector = config("otel-collector.yaml")
    assert collector["exporters"]["prometheus"]["metric_expiration"] == "30s"
    assert collector["exporters"]["prometheus"]["send_timestamps"] is False
    targets = {
        job["job_name"]: job["static_configs"][0]["targets"]
        for job in config("prometheus.yaml")["scrape_configs"]
    }
    assert targets["collector-self"] != targets["collector-telemetry"]
    assert targets["collector-self"] == ["collector:8888"]
    assert targets["collector-telemetry"] == ["collector:8889"]
    assert "remote_write" not in config("prometheus.yaml")


def test_stores_configure_real_retention_and_persistent_paths():
    loki = config("loki.yaml")
    assert loki["limits_config"]["retention_period"] == "72h"
    assert loki["limits_config"]["allow_structured_metadata"] is True
    assert loki["limits_config"]["otlp_config"]["resource_attributes"] == {
        "ignore_defaults": True,
        "attributes_config": [
            {"action": "index_label", "attributes": ["service.name"]}
        ],
    }
    assert loki["compactor"]["retention_enabled"] is True
    assert loki["compactor"]["delete_request_store"] == "filesystem"
    assert loki["compactor"]["working_directory"].startswith("/loki/")
    assert loki["ingester"]["wal"]["dir"].startswith("/loki/")
    for path in loki["storage_config"]["tsdb_shipper"].values():
        assert path.startswith("/loki/")
    tempo = config("tempo.yaml")
    assert tempo["storage"]["trace"]["backend"] == "local"
    assert tempo["storage"]["trace"]["wal"]["path"].startswith("/var/tempo/")
    assert tempo["storage"]["trace"]["local"]["path"].startswith("/var/tempo/")
    assert tempo["compactor"]["compaction"]["block_retention"] == "72h"
    assert "metrics_generator" not in tempo and "cache" not in tempo


def test_grafana_provisions_only_internal_stores_with_stable_links():
    data = config("grafana/provisioning/datasources/datasources.yaml")
    sources = {source["type"]: source for source in data["datasources"]}
    assert set(sources) == {"prometheus", "loki", "tempo"}
    for kind, source in sources.items():
        assert source["uid"] == "restaurantos-" + kind
        assert source["access"] == "proxy" and source["editable"] is False
        assert source["url"].startswith("http://" + kind + ":")
        assert "secureJsonData" not in source
    field = sources["loki"]["jsonData"]["derivedFields"][0]
    assert field["datasourceUid"] == sources["tempo"]["uid"]
    assert field["url"] == "$${__value.raw}"


@pytest.mark.parametrize("failure", ["timeout", "parser-error"])
def test_parser_checker_cleans_only_its_container_and_preserves_failure(
    monkeypatch, failure
):
    spec = importlib.util.spec_from_file_location(
        "monitoring_config_checker", ROOT / "scripts/check-monitoring-config.py"
    )
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    calls = []
    error = (
        subprocess.TimeoutExpired("docker", 120)
        if failure == "timeout"
        else subprocess.CalledProcessError(1, "docker")
    )

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "run":
            raise error
        return subprocess.CompletedProcess(command, 1, "", "No such container")

    monkeypatch.setattr(checker, "require_local_engine", lambda: None)
    monkeypatch.setattr(checker.subprocess, "run", run)
    with pytest.raises(type(error)) as caught:
        checker.main()
    assert caught.value is error
    name = calls[0][calls[0].index("--name") + 1]
    assert name.startswith("restaurantos-monitoring-config-")
    assert calls[1] == ["docker", "rm", "--force", "--volumes", name]
    assert len(calls) == 2


def test_database_redis_receivers_are_opt_in_restricted_and_bounded():
    base = config("otel-collector.yaml")
    diagnostics = config("otel-diagnostics.yaml")
    compose = config("compose.diagnostics.yaml")
    assert set(compose["services"]) == {"collector"}
    assert set(base["receivers"]) == {"otlp"}
    receivers = diagnostics["receivers"]
    for name, receiver in receivers.items():
        assert receiver["username"] == "restaurantos_monitor"
        assert receiver["password"].startswith("${file:/run/secrets/")
        assert receiver["collection_interval"] == "10s"
        assert receiver["timeout"] == "2s"
        assert "events" not in receiver
    pg = receivers["postgresql/diagnostics"]
    assert pg["connect_database"] == pg["databases"][0]
    assert pg["connection_pool"]["max_open"] == 1
    enabled = {name for name, metric in pg["metrics"].items() if metric["enabled"]}
    assert {
        "postgresql.backends",
        "postgresql.rollbacks",
        "postgresql.commits",
        "postgresql.deadlocks",
        "postgresql.database.locks",
        "postgresql.connection.max",
    } <= enabled
    assert not any(
        "table" in name or "index" in name or "query" in name for name in enabled
    )
    statements = diagnostics["processors"]["transform/postgresql"]["metric_statements"]
    assert any(
        "aggregate_on_attributes" in " ".join(group["statements"])
        for group in statements
    )
    assert base["service"]["pipelines"]["metrics/diagnostics"]["processors"] == [
        "memory_limiter",
        "filter/diagnostics",
        "transform/diagnostics",
        "batch",
    ]
