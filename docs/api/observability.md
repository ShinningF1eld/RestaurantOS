# API HTTP observability

Issue #59 adds optional API-boundary telemetry using OpenTelemetry Python SDK
1.45.1 and OTLP/HTTP protobuf. It changes no HTTP routes, bodies, authentication,
database schema, transaction ownership, or health/readiness dependencies.
Optional [Next.js server traces](frontend-observability.md) continue SSR requests through
this API boundary. Database/Redis spans, outbox trace persistence, workers, business metrics
and operator dashboards remain separate M9 work.

## Configuration

Set these in the API environment, independently of optional monitoring startup:

| Setting | Default | Bound/meaning |
|---|---|---|
| `MONITORING_ENABLED` | `false` | No providers/export threads when disabled |
| `MONITORING_ENDPOINT` | `http://localhost:4318` | HTTP(S) origin; no credentials, query or path; host guide below |
| `MONITORING_TRUSTED_UPSTREAM_IPS` | `[]` | JSON list of at most 16 exact peer IPs; incoming traceparent ignored otherwise |
| `MONITORING_EXPORT_TIMEOUT_SECONDS` | `1` | 0.1–2 seconds, SDK HTTP export/retry budget |
| `MONITORING_EXPORT_INTERVAL_MS` | `5000` | 1,000–30,000 ms metric collection interval |
| `MONITORING_QUEUE_SIZE` | `256` | 16–1,024 records **per** log/span queue; oldest records drop on overflow |
| `MONITORING_SHUTDOWN_SECONDS` | `3` | 0.1–5 seconds maximum lifespan wait for background shutdown |

`DATABASE_ECHO=true` is rejected with monitoring enabled: SQLAlchemy echo has
its own logging handler. Production already forbids echo. API diagnostics do
not export SQL text, bound parameters, settings, request/response payloads or
headers. No exporter headers/credentials are supported. Export sessions ignore
proxy/netrc state, strip ambient SDK headers/cookies and refuse redirects. TLS
verification remains enabled. Request IDs are existing public opaque correlation
IDs, limited to 128 safe characters; callers must not put secrets in them.

For host development, start the existing optional monitoring stack and use its
loopback OTLP port (`http://localhost:4318` by default). Use `localhost` for the
API/frontend as before. For an isolated API container on the test monitoring
network, set `MONITORING_ENDPOINT=http://collector:4318`; do not use localhost
to address another container. No application startup dependency on Collector
is introduced. Monitoring stores remain internal and OTLP is a trusted local
ingestion interface, not a public service or authenticated tenant API.

## Instruments and dimensions

All instruments have resource `service.name=restaurantos-api` and scope
`restaurantos.api.http` version `1`:

| OTLP name | Kind/unit | Prometheus series |
|---|---|---|
| `restaurantos.http.requests` | monotonic counter, `1` | `restaurantos_http_requests_total` |
| `restaurantos.http.duration` | explicit histogram, `s` | `restaurantos_http_duration_seconds_{bucket,sum,count}` |
| `restaurantos.http.inflight` | up/down counter, `1` | `restaurantos_http_inflight` (gauge) |
| `restaurantos.http.last_observation` | gauge, `s` since Unix epoch | `restaurantos_http_last_observation_seconds` |

Counts and duration carry `http.route`, `http.request.method`,
`http.response.status_code` and `outcome`. In-flight carries only route/method;
the timestamp has no request dimensions. Routes are registered templates,
including effective router prefixes, resolved from the cached OpenAPI route
table and directly registered hidden routes without executing dependencies.
Unknown paths map to `<unmatched>`; unknown methods map to `OTHER`. No IDs,
query values, bodies, exceptions or trace exemplars enter metrics.

Explicit upper bucket boundaries in seconds are 0.005, 0.01, 0.025, 0.05, 0.1,
0.25, 0.5, 1, 2.5, 5, 10 and 30, plus implicit infinity. For example:

```promql
sum by (http_route) (rate(restaurantos_http_requests_total[5m]))
histogram_quantile(0.95, sum by (le, http_route) (rate(restaurantos_http_duration_seconds_bucket[5m])))
```

Replace 0.95 with 0.50 or 0.99 for P50/P99. Buckets give estimates, not exact
request percentiles. Duration runs from request-boundary entry through response
completion/application unwind, including streaming and background tasks. There
is one completion observation per invocation, including cancellation/failure.
In-flight releases in `finally` with the same attributes used to acquire it.

Outcomes are `success` (<400), `authentication` (401), `forbidden` (403, including
CSRF), `not_found` (404), `conflict` (409), `validation` (422), `rate_limit` (429),
`client_error` (remaining 4xx), `server_error` (5xx or unexpected exception), and
`cancelled`. Cancellation takes precedence; status 0 means cancelled before
response headers, with **no fabricated HTTP response**. If headers were already
sent, their status is retained, including an exception after a 200 response.
Expected 4xx do not set span error status. A 503 dependency failure is a server
error; no exception messages are used for classification.

## Correlation and privacy

The existing request ID is still selected/echoed. JSON request diagnostics also
include current 32-digit trace and 16-digit span IDs when monitoring is active.
Every request creates one SERVER span named `HTTP request`. Only route, method,
status, outcome and request ID are attached; no exception events, stacks, links,
network addresses, SQL, headers or vendor state are captured automatically.

Only a single valid, exact-length W3C version-00 `traceparent` from a configured
peer can continue a trace. Invalid, duplicate, oversized and untrusted headers
start a fresh trace; baggage/tracestate are never extracted. This is independent
of authentication and grants no access. Configure trusted peers narrowly and
run Uvicorn with `--no-proxy-headers` so that peer identity is the socket peer,
not an untrusted forwarded header. Do not broadly trust browser traffic.
Tracing is explicitly 100% at this API boundary, including an upstream unsampled
parent; revisiting sampling/overhead belongs to measured M9 acceptance.

Local JSON formatting renders only fixed approved message templates. Arguments,
free-form library messages, exception text and tracebacks are suppressed;
existing feature-owned safe operational extras remain available. Uvicorn logs
propagate through that formatter instead of its raw URL/traceback handlers.
Remote logs are fixed `HTTP request completed` records with approved attributes
and SDK trace/span correlation; there is no generic logging handler forwarding
arbitrary Python records. No stdout/filelog receiver duplicates them.

Loki log queries expose structured metadata as result labels. Index admission is
checked separately through its series API: only `service_name` is indexed;
request/trace/span IDs remain structured metadata, even when query results display
them alongside index labels.

Collector API pipelines independently validate exact route templates, bounded
methods/outcomes/status, remove resource/scope/schema metadata, extra attributes,
events, links and status text, and fix log body/severity. Synthetic pipelines
remain separate. `service.name` selects a policy; it authenticates nothing.
New public routes require reviewing the Collector's exact route allowlist;
unreviewed signals fail closed rather than accepting arbitrary paths. Prometheus
has a bounded 20,000 workload-sample scrape limit for API histograms; an exceeded
limit fails a scrape rather than silently accepting unlimited series.

## Availability and loss

Providers are local to the API runtime rather than replacing global SDK providers.
One reference-counted process lifecycle shares instruments across overlapping
lifespans. The last owner detaches the runtime and starts daemon shutdown; new
owners fail open with local diagnostics while that runtime retires. Sequential
lifespans can create a fresh runtime after retirement, with fresh process-local
metrics. No duplicate handler or competing live provider set is installed.

Resources are owned immediately during initialization, including exporters,
processors and readers not yet attached to a successfully constructed provider.
A partial initialization failure retires these resources off the event loop.
Retry remains fenced until cleanup succeeds; a cleanup failure leaves monitoring
unavailable for that process instead of accumulating another set of workers.
Application requests still operate, with local failure diagnostics.

SDK workers export log/span batches of at most 16 records; metrics use the SDK's
splitting into at most 16 datapoints per request. Each encoded OTLP request is
capped at 64 KiB, matching Collector. Metric exports aggregate bounded label sets,
with one periodic reader, not an unbounded per-request queue. A metric collection
shares one send deadline across all its batches, limited by the export timeout.
No new transfer starts after that deadline. An in-progress HTTP attempt and SDK
retry backoff are independently bounded and can finish after the send deadline;
this is not a real-time cancellation guarantee. Deadline expiry is terminal for
that collection; the next collection receives a fresh budget and retries the
cumulative snapshot without inflating counters. An individual oversized batch
still fails safely; larger ordinary cumulative snapshots are split. The HTTP
exporter allows at most six attempt rounds within its configured export budget,
with at most one immediate stale-connection recovery per round;
responses are not buffered. No required remote export or flush runs inside a
business transaction or the request event loop. The SDK batch processor's flush
timeout alone is not relied on: shutdown runs on a daemon, and lifespan waits
only its configured budget. Stuck transport cleanup fences reinitialization
instead of accumulating additional exporter sets. Process exit can discard data.

Safe local `telemetry_queue_full` and `telemetry_export_diagnostic` events expose
SDK loss/failure categories without remote messages. Startup/observation/shutdown
failures are similarly local. These are diagnostic observations, not a durable
loss ledger; stderr blocking or process failure can lose them too. Queue loss,
outage and reset cannot be reconstructed from later counter snapshots.

Pair workload queries with Collector/store health, export/enqueue failures and
last-observation age. Collector expires stale workload series after 30 seconds.
An absent/old timestamp, missing scrape or zero traffic in a stopped process is
**unknown/stale**, not healthy zero activity. `/health` and `/ready` never query
monitoring. Business retries must reuse existing idempotency keys after uncertain
failures; missing telemetry never justifies repeating a committed command.
