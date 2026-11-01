import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def producer():
    spec = importlib.util.spec_from_file_location(
        "monitoring_generator", ROOT / "scripts/generate-monitoring-telemetry.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_preserves_trace_parentage_and_log_identity(producer):
    spans, log = producer.operation("test", 1, 1_000_000_000)
    assert spans[1]["parentSpanId"] == spans[0]["spanId"]
    assert log["traceId"] == spans[0]["traceId"] == spans[1]["traceId"]
    assert log["spanId"] == spans[0]["spanId"]
    assert producer.identities("test", 1) != producer.identities("test", 2)


def test_cumulative_histogram_matches_declared_workload(producer):
    metrics = producer.metrics(3600, 1, 2)
    point = metrics[1]["histogram"]["dataPoints"][0]
    assert point["sum"] == 63
    assert point["count"] == "3600"
    assert sum(map(int, point["bucketCounts"])) == 3600
    assert metrics[0]["sum"]["isMonotonic"]
    assert "attributes" not in point


def test_encoded_requests_respect_actual_byte_limit(producer):
    spans = [producer.operation("test", n, 1_000_000_000)[0][0] for n in range(500)]
    bodies = producer.encode("traces", spans)
    assert len(bodies) > 1
    assert all(len(body) <= producer.MAX_REQUEST for body in bodies)
    assert (
        sum(
            len(json.loads(body)["resourceSpans"][0]["scopeSpans"][0]["spans"])
            for body in bodies
        )
        == 500
    )
    with pytest.raises(ValueError):
        producer.encode("logs", [{"body": "x" * 100000}])


def test_uncertain_transport_is_reported_without_replay(producer, monkeypatch):
    calls = []

    class Unavailable:
        def open(self, request, **kwargs):
            calls.append(request)
            raise OSError("synthetic transport failure")

    monkeypatch.setattr(producer, "build_opener", lambda *args: Unavailable())
    monkeypatch.setattr(producer.time, "monotonic", lambda: 0)
    monkeypatch.setattr(producer.time, "sleep", lambda seconds: None)
    result = producer.generate("http://localhost:4318", 1, 1, "test", False)
    assert not result["complete"]
    assert result["failed_or_uncertain_requests"] == 3
    assert result["acknowledged_requests"] == 0
    assert len(calls) == 3
