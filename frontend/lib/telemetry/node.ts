import "server-only";
import { context, propagation, trace } from "@opentelemetry/api";
import { AsyncLocalStorageContextManager } from "@opentelemetry/context-async-hooks";
import { setGlobalErrorHandler } from "@opentelemetry/core";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { AlwaysOnSampler, BatchSpanProcessor, TracerProvider } from "@opentelemetry/sdk-trace";
import type { SpanProcessor } from "@opentelemetry/sdk-trace";
import { monitoringConfig } from "./config";
import { traceContext } from "./context";
import { safeSpan } from "./privacy";

const state = globalThis as typeof globalThis & { restaurantosTracing?: boolean };

export function registerTracing() {
  if (state.restaurantosTracing) return;
  const config = monitoringConfig();
  if (!config) return;
  state.restaurantosTracing = true;
  // One explicit API client span; disable Next's overlapping raw-URL fetch span.
  process.env.NEXT_OTEL_FETCH_DISABLED = "1";
  setGlobalErrorHandler(() => console.warn("telemetry_export_failed"));
  const exporter = new OTLPTraceExporter({
    url: `${config.endpoint}/v1/traces`,
    timeoutMillis: config.timeout,
    concurrencyLimit: 1,
    headers: async () => ({}),
    httpAgentOptions: { keepAlive: false },
  });
  const batch = new BatchSpanProcessor({
    exporter,
    maxQueueSize: config.queue,
    maxExportBatchSize: 16,
    scheduledDelayMillis: 1000,
    exportTimeoutMillis: config.timeout,
  });
  const processor: SpanProcessor = {
    onStart() {},
    onEnd: (span) => batch.onEnd(safeSpan(span)),
    forceFlush: () => batch.forceFlush(),
    shutdown: () => batch.shutdown(),
  };
  const provider = new TracerProvider({
    resource: resourceFromAttributes({ "service.name": "restaurantos-frontend" }),
    sampler: new AlwaysOnSampler(),
    spanProcessors: [processor],
    spanLimits: {
      attributeCountLimit: 32,
      attributeValueLengthLimit: 128,
      eventCountLimit: 0,
      linkCountLimit: 0,
    },
  });
  context.setGlobalContextManager(new AsyncLocalStorageContextManager().enable());
  propagation.setGlobalPropagator(traceContext);
  trace.setGlobalTracerProvider(provider);
  let stopping = false;
  const shutdown = () => {
    if (stopping) return;
    stopping = true;
    // Next owns signals/exit. Never delay it or impose a request-time flush.
    const deadline = setTimeout(() => console.warn("telemetry_shutdown_timeout"), config.shutdown);
    deadline.unref();
    void provider
      .shutdown()
      .catch(() => console.warn("telemetry_shutdown_failed"))
      .finally(() => clearTimeout(deadline));
  };
  process.once("SIGTERM", shutdown);
  process.once("SIGINT", shutdown);
}
