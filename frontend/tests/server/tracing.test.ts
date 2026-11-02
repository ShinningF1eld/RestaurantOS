// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { createServer } from "node:http";
import { once } from "node:events";
import { context, propagation, ROOT_CONTEXT, SpanKind, trace } from "@opentelemetry/api";
import { AsyncLocalStorageContextManager } from "@opentelemetry/context-async-hooks";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import {
  InMemorySpanExporter,
  SimpleSpanProcessor,
  TracerProvider,
  type ReadableSpan,
} from "@opentelemetry/sdk-trace";
import { monitoringConfig } from "@/lib/telemetry/config";
import { apiTraceHeaders, traceContext, validTraceparent } from "@/lib/telemetry/context";
import { safeSpan } from "@/lib/telemetry/privacy";

vi.mock("server-only", () => ({}));
const mocks = vi.hoisted(() => ({
  cookie: "synthetic-access",
  redirect: vi.fn(),
  headers: new Headers(),
}));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (name === "ros_access" ? { value: mocks.cookie } : undefined),
  }),
  headers: async () => mocks.headers,
}));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));

afterEach(() => {
  trace.disable();
  context.disable();
  propagation.disable();
  vi.unstubAllEnvs();
});

describe("server trace boundary", () => {
  it("initializes only once and disabled configuration creates no provider", async () => {
    const previousTerm = new Set(process.listeners("SIGTERM"));
    const previousInt = new Set(process.listeners("SIGINT"));
    const registration = vi.spyOn(trace, "setGlobalTracerProvider");
    const { registerTracing } = await import("@/lib/telemetry/node");
    vi.stubEnv("MONITORING_ENABLED", "false");
    registerTracing();
    expect(registration).not.toHaveBeenCalled();
    vi.stubEnv("MONITORING_ENABLED", "true");
    vi.stubEnv("MONITORING_ENDPOINT", "http://127.0.0.1:1");
    try {
      registerTracing();
      registerTracing();
      expect(registration).toHaveBeenCalledTimes(1);
    } finally {
      const provider = registration.mock.calls[0]?.[0] as TracerProvider | undefined;
      await provider?.shutdown();
      for (const listener of process.listeners("SIGTERM"))
        if (!previousTerm.has(listener)) process.removeListener("SIGTERM", listener);
      for (const listener of process.listeners("SIGINT"))
        if (!previousInt.has(listener)) process.removeListener("SIGINT", listener);
      delete (globalThis as typeof globalThis & { restaurantosTracing?: boolean })
        .restaurantosTracing;
    }
  });

  it("validates explicit bounded configuration without rendering secret values", () => {
    expect(monitoringConfig({})).toBeNull();
    expect(
      monitoringConfig({ MONITORING_ENABLED: "false", MONITORING_ENDPOINT: "invalid" }),
    ).toBeNull();
    expect(monitoringConfig({ MONITORING_ENABLED: "true" })?.queue).toBe(256);
    for (const endpoint of [
      "invalid-canary",
      "http://user:canary@localhost", // pragma: allowlist secret -- synthetic rejection fixture
      "http://localhost/private",
      "http://localhost/?secret=canary",
      "file:///tmp",
    ]) {
      expect(() =>
        monitoringConfig({ MONITORING_ENABLED: "true", MONITORING_ENDPOINT: endpoint }),
      ).toThrow("Invalid MONITORING_ENDPOINT");
    }
    for (const value of ["0", "1025", "NaN", "1.5", "-2"]) {
      expect(() =>
        monitoringConfig({ MONITORING_ENABLED: "true", MONITORING_QUEUE_SIZE: value }),
      ).toThrow("Invalid MONITORING_QUEUE_SIZE");
    }
  });

  it("extracts only exact valid version-00 parents and never injects ambient metadata", () => {
    const parent = "00-12345678901234567890123456789012-1234567890123456-01";
    const getter = { keys: Object.keys, get: (c: Record<string, string>, k: string) => c[k] };
    for (const value of [
      undefined,
      "bad",
      parent + "," + parent,
      parent.replace("1234567890123456-", "0000000000000000-"),
      parent.replace("00-", "ff-"),
      parent.replace(/01$/, "ff"),
    ]) {
      expect(validTraceparent(value)).toBe(false);
      expect(
        trace.getSpanContext(traceContext.extract(ROOT_CONTEXT, { traceparent: value }, getter)),
      ).toBeUndefined();
    }
    const extracted = traceContext.extract(
      ROOT_CONTEXT,
      { traceparent: parent, baggage: "secret=canary", tracestate: "vendor=canary" },
      getter,
    );
    expect(trace.getSpanContext(extracted)?.traceId).toBe(parent.slice(3, 35));
    expect(trace.getSpanContext(extracted)?.traceState).toBeUndefined();
    const carrier = {};
    traceContext.inject();
    expect(carrier).toEqual({});
    context.setGlobalContextManager(new AsyncLocalStorageContextManager().enable());
    context.with(extracted, () => {
      expect(apiTraceHeaders(new URL("http://api:8000/api/access"), "http://api:8000")).toEqual({
        traceparent: parent,
      });
      expect(apiTraceHeaders(new URL("http://external/api/access"), "http://api:8000")).toEqual({});
      expect(apiTraceHeaders(new URL("http://user:pass@api:8000/"), "http://api:8000")).toEqual({}); // pragma: allowlist secret -- synthetic rejection fixture
    });
  });

  it("preserves cookie, no-store, redirect rejection and browser renewal on SSR 401", async () => {
    const exporter = new InMemorySpanExporter();
    const provider = new TracerProvider({
      spanProcessors: [new SimpleSpanProcessor({ exporter })],
    });
    trace.setGlobalTracerProvider(provider);
    context.setGlobalContextManager(new AsyncLocalStorageContextManager().enable());
    vi.stubEnv("API_URL", "http://api:8000");
    mocks.headers.set("x-restaurantos-path", "//untrusted.example");
    mocks.redirect.mockImplementation(() => {
      throw new Error("renewal redirect");
    });
    const fetch = vi.fn().mockResolvedValue(new Response("{}", { status: 401 }));
    vi.stubGlobal("fetch", fetch);
    const { getAccess } = await import("@/lib/api/server");
    await expect(getAccess()).rejects.toThrow("renewal redirect");
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe("http://api:8000/api/access");
    expect(options.cache).toBe("no-store");
    expect(options.redirect).toBe("error");
    expect(Object.keys(options.headers).sort()).toEqual(["Cookie", "traceparent"]);
    expect(options.headers.Cookie).toBe("ros_access=synthetic-access");
    expect(validTraceparent(options.headers.traceparent)).toBe(true);
    expect(mocks.redirect).toHaveBeenCalledWith("/session/renew?next=%2Fdashboard%2Frestaurants");
    expect(exporter.getFinishedSpans()).toHaveLength(1);
    await provider.shutdown();
  });

  it("exports actual OTLP without canaries from framework-like URLs and exception paths", async () => {
    const payloads: string[] = [];
    const server = createServer((req, res) => {
      let body = "";
      req.on("data", (data) => {
        body += data;
      });
      req.on("end", () => {
        payloads.push(body);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end("{}");
      });
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const address = server.address() as { port: number };
    const exporter = new OTLPTraceExporter({
      url: `http://127.0.0.1:${address.port}/v1/traces`,
      headers: async () => ({}),
      timeoutMillis: 500,
    });
    const snapshots: ReadableSpan[] = [];
    const provider = new TracerProvider({
      spanProcessors: [
        {
          onStart() {},
          onEnd: (span) => {
            snapshots.push(safeSpan(span));
          },
          shutdown: async () => {},
          forceFlush: async () => {},
        },
      ],
    });
    try {
      const canary = "SYNTHETIC-SECRET-CANARY";
      const span = provider.getTracer(canary).startSpan(`GET /${canary}?password=${canary}`, {
        kind: SpanKind.SERVER,
        attributes: {
          "http.url": canary,
          "next.route": `/${canary}`,
          Cookie: canary,
          Authorization: canary,
          body: canary,
          html: canary,
        },
      });
      span.recordException(new Error(canary));
      span.setStatus({ code: 2, message: canary });
      span.end();
      await new Promise<void>((resolve, reject) =>
        exporter.export(snapshots, (result) =>
          result.code === 0 ? resolve() : reject(result.error ?? new Error("export failed")),
        ),
      );
      expect(payloads).toHaveLength(1);
      expect(payloads[0]).not.toContain(canary);
      expect(payloads[0]).toContain("restaurantos-frontend");
      expect(payloads[0]).toContain("Next.js request");
      expect(payloads[0]).toContain("<unmatched>");
    } finally {
      await provider.shutdown();
      await exporter.shutdown();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it.each(["slow", "retryable"])(
    "bounds real exporter attempts against a %s receiver",
    async (mode) => {
      let attempts = 0;
      const server = createServer((req, res) => {
        attempts++;
        req.resume();
        if (mode === "retryable") {
          res.writeHead(503, { "Retry-After": "0" });
          res.end();
        }
      });
      server.listen(0, "127.0.0.1");
      await once(server, "listening");
      const address = server.address() as { port: number };
      const exporter = new OTLPTraceExporter({
        url: `http://127.0.0.1:${address.port}/v1/traces`,
        timeoutMillis: 100,
        concurrencyLimit: 1,
        headers: async () => ({}),
      });
      const snapshots: ReadableSpan[] = [];
      const provider = new TracerProvider({
        spanProcessors: [
          {
            onStart() {},
            onEnd: (span) => {
              snapshots.push(safeSpan(span));
            },
            shutdown: async () => {},
            forceFlush: async () => {},
          },
        ],
      });
      try {
        provider.getTracer("test").startSpan("synthetic").end();
        const started = performance.now();
        const result = await new Promise<{ code: number }>((resolve) =>
          exporter.export(snapshots, resolve),
        );
        expect(result.code).toBe(1);
        expect(performance.now() - started).toBeLessThan(1500);
        expect(attempts).toBeGreaterThan(0);
        expect(attempts).toBeLessThanOrEqual(6);
        await exporter.shutdown();
      } finally {
        await provider.shutdown();
        server.closeAllConnections();
        await new Promise<void>((resolve) => server.close(() => resolve()));
      }
    },
  );
});
