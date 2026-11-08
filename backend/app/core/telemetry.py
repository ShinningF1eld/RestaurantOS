"""Optional process-owned SDK pipelines. No global OTel provider or auto-instrumentation.

Only immutable, bounded operational records cross this boundary. SDK workers own
all network IO; request handling only measures/enqueues. Retiring providers fence
new lifespans until shutdown completes, preventing accumulating exporter threads.
"""

import logging
from contextvars import ContextVar
from threading import Event, Lock, Thread
from time import monotonic
from typing import TYPE_CHECKING, Any

import requests
from starlette.types import Scope
from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk._logs import LoggerProvider, LogRecordLimits
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import AlwaysOffExemplarFilter, MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.export import MetricsData, MetricExportResult
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from app.core.config import Settings
from app.core.diagnostics import Diagnostics

if TYPE_CHECKING:
    from app.core.business_collection import BusinessCollector

SCOPE = "restaurantos.api.http"
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
logger = logging.getLogger("restaurantos.telemetry")
_export_deadline: ContextVar[float | None] = ContextVar(
    "metric_export_deadline", default=None
)


class ExportBudgetExpired(Exception):
    """A local budget expiry, deliberately not a retryable connection failure."""


class InitializationFailed(Exception):
    def __init__(self, runtime: "Telemetry") -> None:
        super().__init__("Telemetry initialization failed")
        self.runtime = runtime


class ExportSession(requests.Session):
    """Strip ambient SDK headers, credentials, cookies and redirect forwarding."""

    def send(
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        deadline = _export_deadline.get()
        if deadline is not None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ExportBudgetExpired()
            kwargs["timeout"] = min(kwargs.get("timeout") or remaining, remaining)
        if not isinstance(request.body, bytes):
            raise ValueError("Only encoded OTLP payloads are supported")
        request.headers = requests.structures.CaseInsensitiveDict(
            {
                "Content-Type": "application/x-protobuf",
                "Content-Length": str(len(request.body or b"")),
            }
        )
        kwargs.update(
            allow_redirects=False, verify=True, cert=None, proxies={}, stream=True
        )
        try:
            response = super().send(request, **kwargs)
        except requests.Timeout:
            if deadline is not None and monotonic() >= deadline:
                raise ExportBudgetExpired() from None
            raise
        # The SDK checks status only. Never buffer an arbitrary Collector body.
        response.close()
        if deadline is not None and monotonic() >= deadline:
            raise ExportBudgetExpired()
        return response


class BudgetedMetricExporter(OTLPMetricExporter):
    """SDK datapoint splitting with one send deadline across the whole snapshot.

    A terminal local error stops the SDK's batch loop once the budget expires.
    Each later collection gets a fresh budget, including after failed exports.
    SDK retry backoff and an in-progress HTTP attempt remain independently bounded.
    """

    def __init__(self, *, budget_seconds: float, **kwargs: Any) -> None:
        self.budget_seconds = budget_seconds
        super().__init__(max_export_batch_size=16, **kwargs)

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float | None = 10000,
        **kwargs: Any,
    ) -> MetricExportResult:
        budget = self.budget_seconds
        if timeout_millis is not None:
            budget = min(budget, max(0, timeout_millis / 1000))
        token = _export_deadline.set(monotonic() + budget)
        try:
            return super().export(metrics_data, timeout_millis=budget * 1000, **kwargs)
        finally:
            _export_deadline.reset(token)


def exporter_options(settings: Settings, signal: str) -> dict:
    session = ExportSession()
    # Local OTLP must not inherit proxy credentials, netrc or ambient OTEL headers.
    session.trust_env = False
    return {
        "endpoint": f"{settings.monitoring_endpoint}/v1/{signal}",
        "headers": {},
        "timeout": settings.monitoring_export_timeout_seconds,
        "compression": Compression.NoCompression,
        "session": session,
        "max_request_size": 65536,
        "meter_provider": NoOpMeterProvider(),
    }


class Telemetry:
    business_collector: "BusinessCollector | None"

    def __init__(self, settings: Settings, role: str = "api") -> None:
        self.settings = settings
        self.providers: list = []
        self.pending: list = []
        self.business_collector = None
        try:
            resource = Resource({"service.name": "restaurantos-" + role})
            self.traces = TracerProvider(
                resource=resource,
                sampler=ALWAYS_ON,
                shutdown_on_exit=False,
                span_limits=SpanLimits(
                    max_attributes=16 if role == "worker" else 8,
                    max_events=0,
                    max_links=1 if role == "worker" else 0,
                    max_attribute_length=128,
                ),
            )
            self.providers.append(self.traces)
            trace_exporter = self._own(
                OTLPSpanExporter(**exporter_options(settings, "traces"))
            )
            trace_processor = self._own(
                BatchSpanProcessor(
                    trace_exporter,
                    max_queue_size=settings.monitoring_queue_size,
                    max_export_batch_size=16,
                    schedule_delay_millis=1000,
                    export_timeout_millis=int(
                        settings.monitoring_export_timeout_seconds * 1000
                    ),
                )
            )
            self.pending.remove(trace_exporter)
            self.traces.add_span_processor(trace_processor)
            self.pending.remove(trace_processor)
            self.logs = LoggerProvider(
                resource=resource,
                shutdown_on_exit=False,
                log_record_limits=LogRecordLimits(
                    max_attributes=8, max_attribute_length=128
                ),
            )
            self.providers.append(self.logs)
            log_exporter = self._own(
                OTLPLogExporter(**exporter_options(settings, "logs"))
            )
            log_processor = self._own(
                BatchLogRecordProcessor(
                    log_exporter,
                    max_queue_size=settings.monitoring_queue_size,
                    max_export_batch_size=16,
                    schedule_delay_millis=1000,
                    export_timeout_millis=int(
                        settings.monitoring_export_timeout_seconds * 1000
                    ),
                )
            )
            self.pending.remove(log_exporter)
            self.logs.add_log_record_processor(log_processor)
            self.pending.remove(log_processor)
            metric_exporter = self._own(
                BudgetedMetricExporter(
                    budget_seconds=settings.monitoring_export_timeout_seconds,
                    **exporter_options(settings, "metrics"),
                )
            )
            reader = self._own(
                PeriodicExportingMetricReader(
                    metric_exporter,
                    export_interval_millis=settings.monitoring_export_interval_ms,
                    export_timeout_millis=int(
                        settings.monitoring_export_timeout_seconds * 1000
                    ),
                )
            )
            self.pending.remove(metric_exporter)
            self.metrics = MeterProvider(
                resource=resource,
                metric_readers=[reader],
                shutdown_on_exit=False,
                exemplar_filter=AlwaysOffExemplarFilter(),
                views=[
                    View(
                        instrument_name="restaurantos.*duration",
                        aggregation=ExplicitBucketHistogramAggregation(BUCKETS),
                    )
                ],
            )
            self.providers.append(self.metrics)
            self.pending.remove(reader)
            self.diagnostics = Diagnostics(
                self.metrics, role, settings.monitoring_worker_slot
            )
            if role == "api":
                from app.core.business_metrics import BusinessMetrics

                self.business_metrics = BusinessMetrics(self.metrics)
                if settings.monitoring_business_aggregates_enabled:
                    from app.core.business_collection import BusinessCollector

                    self.business_collector = BusinessCollector(
                        self.business_metrics.meter, settings
                    )
            if role == "worker":
                from app.modules.events.telemetry import WorkerMetrics

                self.worker_metrics = WorkerMetrics(
                    self.metrics, settings.monitoring_worker_slot
                )
                if settings.monitoring_worker_slot is None:
                    logger.warning("worker process metrics require slot")
            meter = self.metrics.get_meter(SCOPE, "1")
            self.requests = meter.create_counter("restaurantos.http.requests", unit="1")
            self.duration = meter.create_histogram(
                "restaurantos.http.duration", unit="s"
            )
            self.inflight = meter.create_up_down_counter(
                "restaurantos.http.inflight", unit="1"
            )
            self.observed = meter.create_gauge(
                "restaurantos.http.last_observation", unit="s"
            )
            self.tracer = self.traces.get_tracer(SCOPE, "1")
            self.log = self.logs.get_logger(SCOPE, "1")
        except Exception:
            # The lifecycle manager retires partial resources off the event loop.
            raise InitializationFailed(self) from None

    def _own(self, resource: Any) -> Any:
        """Own a resource until a successfully constructed SDK parent adopts it."""
        self.pending.append(resource)
        return resource

    def shutdown(self) -> bool:
        complete = True
        for resource in [*reversed(self.pending), *reversed(self.providers)]:
            try:
                resource.shutdown()
            except Exception:
                complete = False
                logger.warning("telemetry shutdown failed")
        return complete

    def completed(self, attributes: dict, seconds: float, request_id: str) -> None:
        import time

        self.requests.add(1, attributes)
        self.duration.record(seconds, attributes)
        self.observed.set(time.time())
        self.log.emit(
            body="HTTP request completed",
            severity_number=SeverityNumber.INFO,
            severity_text="INFO",
            attributes={**attributes, "request_id": request_id},
        )


class TelemetryLifecycle:
    """Reference-count overlapping owners; fail open while a pipeline retires."""

    def __init__(self, role: str = "api") -> None:
        self.role = role
        self.lock = Lock()
        self.runtime: Telemetry | None = None
        self.owners = 0
        self.retiring: Telemetry | None = None
        self.retired = Event()
        self.retired.set()

    def acquire(self, settings: Settings) -> Telemetry | None:
        if not settings.monitoring_enabled:
            return None
        with self.lock:
            if not self.retired.is_set():
                logger.warning("telemetry retiring")
                return None
            if self.runtime is None:
                try:
                    self.runtime = (
                        Telemetry(settings)
                        if self.role == "api"
                        else Telemetry(settings, role=self.role)
                    )
                except InitializationFailed as error:
                    self._retire(error.runtime)
                    logger.warning("telemetry startup failed")
                    return None
                except Exception:
                    logger.warning("telemetry startup failed")
                    return None
            self.owners += 1
            return self.runtime

    def release(self, runtime: Telemetry | None) -> Event:
        with self.lock:
            if runtime is None or runtime is not self.runtime:
                complete = Event()
                complete.set()
                return complete
            self.owners -= 1
            if self.owners:
                complete = Event()
                complete.set()
                return complete
            self.runtime = None
            return self._retire(runtime)

    def _retire(self, runtime: Telemetry) -> Event:
        self.retiring = runtime
        self.retired.clear()

        def stop() -> None:
            try:
                if runtime.shutdown():
                    self.retiring = None
                    self.retired.set()
            except Exception:
                logger.warning("telemetry shutdown failed")

        try:
            Thread(
                target=stop, name=f"{self.role}-telemetry-shutdown", daemon=True
            ).start()
        except Exception:
            # Keep the failed runtime fenced, even if cleanup cannot be started.
            logger.warning("telemetry shutdown failed")
        return self.retired


lifecycle = TelemetryLifecycle()
worker_lifecycle = TelemetryLifecycle("worker")


def correlation() -> dict[str, str]:
    context = trace.get_current_span().get_span_context()
    return (
        {"trace_id": f"{context.trace_id:032x}", "span_id": f"{context.span_id:016x}"}
        if context.is_valid
        else {}
    )


def trusted_context(scope: Scope, settings: Settings) -> Context:
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator,
    )

    peer = scope.get("client")
    if not peer or peer[0] not in settings.monitoring_trusted_upstream_ips:
        return Context()
    # W3C version 00 only, exact length, one header. Never extract tracestate/baggage.
    values = [v for k, v in scope.get("headers", []) if k.lower() == b"traceparent"]
    if len(values) != 1 or len(values[0]) != 55 or not values[0].startswith(b"00-"):
        return Context()
    try:
        return TraceContextTextMapPropagator().extract(
            {"traceparent": values[0].decode("ascii")}, context=Context()
        )
    except (ValueError, UnicodeError):
        return Context()
