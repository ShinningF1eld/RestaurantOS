import type { ReadableSpan } from "@opentelemetry/sdk-trace";
import { SpanKind } from "@opentelemetry/api";
import { resourceFromAttributes } from "@opentelemetry/resources";

const resource = resourceFromAttributes({ "service.name": "restaurantos-frontend" });
const routes = new Set([
  "/",
  "/login",
  "/session/renew",
  "/dashboard/restaurants",
  ...["dashboard", "employees", "inventory", "orders", "menu", "menu/[menu_id]"].map(
    (suffix) => `/restaurants/[restaurant_id]/${suffix}`,
  ),
]);

// Framework spans can contain raw URLs, exception stacks and rendered data.
// Snapshot an allowlist before queueing; never pass original span objects to export.
export function safeSpan(span: ReadableSpan): ReadableSpan {
  const spanContext = span.spanContext();
  const parent = span.parentSpanContext;
  const route = span.attributes["next.route"] ?? span.attributes["http.route"];
  return {
    name:
      span.kind === SpanKind.SERVER
        ? "Next.js request"
        : span.kind === SpanKind.CLIENT
          ? "API request"
          : "Next.js render",
    kind: span.kind,
    spanContext: () => ({
      traceId: spanContext.traceId,
      spanId: spanContext.spanId,
      traceFlags: spanContext.traceFlags,
    }),
    parentSpanContext: parent
      ? { traceId: parent.traceId, spanId: parent.spanId, traceFlags: parent.traceFlags }
      : undefined,
    startTime: span.startTime,
    endTime: span.endTime,
    duration: span.duration,
    status: { code: span.status.code },
    attributes: {
      "http.route": typeof route === "string" && routes.has(route) ? route : "<unmatched>",
    },
    events: [],
    links: [],
    ended: true,
    resource,
    instrumentationScope: { name: "restaurantos.frontend", version: "1" },
    droppedAttributesCount: 0,
    droppedEventsCount: 0,
    droppedLinksCount: 0,
  };
}
