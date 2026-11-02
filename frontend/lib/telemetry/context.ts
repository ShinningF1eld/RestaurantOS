import {
  context,
  isSpanContextValid,
  trace,
  type Context,
  type TextMapGetter,
} from "@opentelemetry/api";

// Deliberately version 00 only, matching the API contract. Never extract vendor state/baggage.
export function validTraceparent(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]$/.test(value) &&
    !/^00-0{32}-/.test(value) &&
    !/-0{16}-/.test(value)
  );
}

export const traceContext = {
  fields: () => ["traceparent"],
  // No ambient injection: the API client is the only approved outbound boundary.
  inject: () => {},
  extract(carrierContext: Context, carrier: unknown, getter: TextMapGetter) {
    const value = getter.get(carrier, "traceparent");
    if (!validTraceparent(value)) return carrierContext;
    return trace.setSpanContext(carrierContext, {
      traceId: value.slice(3, 35),
      spanId: value.slice(36, 52),
      traceFlags: Number.parseInt(value.slice(53), 16),
      isRemote: true,
    });
  },
};

export function apiTraceHeaders(destination: URL, trustedOrigin: string): Record<string, string> {
  if (destination.origin !== trustedOrigin || destination.username || destination.password)
    return {};
  const span = trace.getSpanContext(context.active());
  if (!span || !isSpanContextValid(span)) return {};
  const value = `00-${span.traceId}-${span.spanId}-${span.traceFlags & 1 ? "01" : "00"}`;
  return validTraceparent(value) ? { traceparent: value } : {};
}
