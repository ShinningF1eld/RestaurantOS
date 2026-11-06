"""Real native Prometheus translation of independent bounded worker streams."""

from contextlib import ExitStack

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, MetricExportResult
from opentelemetry.sdk.resources import Resource

from app.core.diagnostics import Diagnostics
from app.modules.events.repo.worker_queries import BacklogSample
from app.modules.events.telemetry import WorkerMetrics
from support.worker_collector import worker_collector, scrape_metrics
from test_support.monitoring_environment import wait_until


def series(text, name):
    import re
    from types import SimpleNamespace

    # This probe emits only controlled ASCII labels and disables timestamps.
    return [
        SimpleNamespace(
            labels=dict(re.findall(r'(\w+)="([^"\\]*)"', line)),
            value=float(line.rsplit(" ", 1)[1]),
        )
        for line in text.splitlines()
        if line.startswith(name + "{")
    ]


def test_native_worker_streams_quiet_export_and_slot_restart():
    with worker_collector() as (endpoint, scrape), ExitStack() as stack:
        exporter = OTLPMetricExporter(endpoint=endpoint, timeout=2)
        stack.callback(exporter.shutdown)

        def producer(slot, count):
            reader = InMemoryMetricReader()
            provider = MeterProvider(
                resource=Resource({"service.name": "restaurantos-worker"}),
                metric_readers=[reader],
                shutdown_on_exit=False,
            )
            stack.callback(provider.shutdown)
            worker = WorkerMetrics(provider, slot)
            diagnostics = Diagnostics(provider, "worker", slot)
            for _ in range(count):
                worker.completed(
                    0.25,
                    {
                        "operation": "consumer",
                        "consumer": "analytics",
                        "event_type": "order.completed.v1",
                        "outcome": "consumer_committed",
                    },
                )
                diagnostics.record(
                    "sql.slow",
                    1,
                    {"role": "worker", "operation": "SELECT", "outcome": "success"},
                )
            worker.snapshot([BacklogSample("analytics", "queued", 12, 100)])
            worker.progress_snapshot([("analytics", 14, 1000)])
            return reader, provider

        def export(reader):
            assert (
                exporter.export(reader.get_metrics_data()) == MetricExportResult.SUCCESS
            )

        def check(expected):
            text = scrape_metrics(scrape)
            samples = series(text, "restaurantos_worker_operations_total")
            actual = {s.labels["worker_slot"]: s.value for s in samples}
            return (
                text if actual == expected and len(samples) == len(expected) else None
            )

        first, first_provider = producer(0, 5)
        second, _ = producer(1, 9)
        export(first)
        wait_until(lambda: check({"0": 5}), timeout=10)
        export(second)
        wait_until(lambda: check({"0": 5, "1": 9}), timeout=10)
        export(first)  # Quiet re-export must not reset or erase the second stream.
        text = wait_until(lambda: check({"0": 5, "1": 9}), timeout=10)
        assert (
            sum(s.value for s in series(text, "restaurantos_worker_operations_total"))
            == 14
        )
        durations = series(text, "restaurantos_worker_duration_seconds_count")
        assert {s.labels["worker_slot"]: s.value for s in durations} == {"0": 5, "1": 9}
        assert {
            s.labels["worker_slot"]: s.value
            for s in series(text, "restaurantos_sql_slow_total")
        } == {"0": 5, "1": 9}
        depths = [
            s
            for s in series(text, "restaurantos_worker_deliveries_ratio")
            if s.labels["consumer"] == "analytics" and s.labels["state"] == "queued"
        ]
        assert len(depths) == 1 and depths[0].value == 12
        assert "worker_slot" not in depths[0].labels
        first_provider.shutdown()
        restarted, _ = producer(0, 1)
        export(restarted)
        wait_until(lambda: check({"0": 1, "1": 9}), timeout=10)
        export(second)
        wait_until(lambda: check({"0": 1, "1": 9}), timeout=10)
        unassigned, _ = producer(None, 17)
        export(unassigned)
        wait_until(lambda: check({"0": 1, "1": 9}), timeout=10)
