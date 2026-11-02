# Next.js server traces

Issue #60 adds optional server tracing through the existing SSR API client. Direct
browser API calls begin at FastAPI; browser SDKs, interaction capture, navigation
timings, frontend metrics and remote frontend log ingestion remain deferred.
No schema, endpoint, session, CSRF or tenancy policy changes are introduced.

## Runtime configuration

These private variables are read at server startup, never through `next.config.env`
or `NEXT_PUBLIC_*`. The same standalone image uses different runtime endpoints.

| Variable | Default | Accepted values |
|---|---|---|
| `MONITORING_ENABLED` | `false` | Exactly `true` or `false`; disabled creates no SDK |
| `MONITORING_ENDPOINT` | `http://localhost:4318` | HTTP(S) origin without credentials, path, query or fragment |
| `MONITORING_EXPORT_TIMEOUT_MS` | `1000` | Integer 100–2000 milliseconds |
| `MONITORING_QUEUE_SIZE` | `256` | Integer 16–1024 spans |
| `MONITORING_SHUTDOWN_MS` | `3000` | Integer 100–5000 milliseconds; shutdown diagnostic deadline |

Invalid enabled configuration fails startup with the setting name only. Disabled
tracing ignores exporter settings. Collector availability is never probed during
startup and never changes rendering or authentication responses.

Host development uses private `API_URL=http://localhost:8000` and
`MONITORING_ENDPOINT=http://localhost:4318` with the monitoring host overlay. Both
frontend and API use `localhost` for host-only cookies. In containers on the
monitoring network, use `API_URL=http://api:8000` (the API's actual network alias)
and `MONITORING_ENDPOINT=http://collector:4318`. Attach the server to the existing
network; no additional service is needed. See the [monitoring guide](../../monitoring/README.md).

FastAPI separately requires `MONITORING_ENABLED=true` and its own reachable
Collector endpoint. Set `MONITORING_TRUSTED_UPSTREAM_IPS` to the exact frontend
socket peer(s), using the existing [API contract](observability.md). For host SSR
this is normally `127.0.0.1`; container tests discover the frontend container IP
and configure it explicitly. Do not trust forwarded addresses or entire networks
to compensate for a missing peer configuration. Context is diagnostic data and
never authorization evidence.

## Instrumentation and boundaries

The installed Next.js 16.3.7 instrumentation, OpenTelemetry, deployment, runtime
and serverExternalPackages guides were consulted. `instrumentation.ts` imports
Node initialization only for `NEXT_RUNTIME=nodejs`. Next's built-in server/render
spans share an AsyncLocalStorage context with the API client's CLIENT span.
The process-global guard prevents repeated registration.

OpenTelemetry's consolidated tracing SDK 2.12.0 and matching OTLP/HTTP JSON
exporter 0.223.0 are pinned in the npm lock. The older `sdk-trace-node` and
`sdk-trace-base` packages are deprecated; using the tracing provider directly
avoids automatic metrics/log pipelines, resource/environment detection and extra
HTTP instrumentations. Next's overlapping fetch instrumentation is disabled with
its documented `NEXT_OTEL_FETCH_DISABLED` switch when monitoring is enabled.
No custom fetch monkey patch or browser SDK is installed.

The inbound propagator accepts only a single exact lowercase version-00
`traceparent`, nonzero trace/span IDs and flags 00/01. Missing, malformed,
duplicate and oversized values start a fresh trace. It extracts neither baggage
nor vendor state and injects nothing globally. Only the existing server API
client constructs an outbound header from the active CLIENT span and validates
it against the configured API origin. Other destinations receive no ambient
propagation. Requests keep `redirect: "error"`, preventing a second destination
from receiving cookies/context, and `cache: "no-store"`.
Client spans represent logical API reads. Next.js can coalesce identical fetches
within a render; the actual API request retains the initiating read's parent.
Its existing fetch deduplication behavior is preserved.

The API client still forwards only `ros_access` for authentication. A 401 redirects
to `/session/renew` with the existing safe return-path validation; no cookies are
rotated by SSR, and authentication requests are never replayed by instrumentation.

## Privacy, availability and loss

Service identity is `restaurantos-frontend`; exported scope is
`restaurantos.frontend` version `1`. Before entering the bounded batch queue,
every span (including framework and exception paths) becomes a new allowlisted
snapshot: fixed request/render/API names, span kind/timing/IDs/status code and an
exact registered frontend route template or `<unmatched>`. Raw span names, URLs,
query values, events, exception text/stacks, links, vendor state, resource/scope
metadata, payloads and rendered content are omitted. Cookie/header/body capture
is not installed. New frontend route templates require reviewing both source and
Collector allowlists. The Collector independently filters frontend traces and
does not ingest frontend stdout. Existing Next.js local console output is not a
remote log feed; do not add a filelog/stdout receiver without a separate privacy
review. Exporter failure messages use fixed local categories without raw errors.

Sampling is explicitly 100% for this local diagnostic slice, independently of an
incoming unsampled flag. One batch processor queues at most the configured span
count, batches at most 16, exports every second and permits only one HTTP export
at a time. Queue overflow discards telemetry; no request flush runs. SDK retries
have at most five retries within the export time budget (backoff can extend the
last attempt beyond the remaining budget); HTTP timeout remains bounded. The
exporter uses no ambient OTLP credentials, does not follow redirects and does not
use browser fetch or proxy/netrc credentials.

SIGTERM/SIGINT begin best-effort shutdown once. Next.js retains ownership of exit;
shutdown never holds a request or delays Next's exit to guarantee delivery. A
nonblocking deadline emits a fixed timeout diagnostic; in-flight/queued spans
may be lost at exit or during outage. This is disposable telemetry, not a loss
ledger, audit store or application readiness dependency. The focused container
test measures actual stopped-Collector exit with a six-second container grace
period and rejects forced kills; Next's HTTP drain is separate from the telemetry
diagnostic deadline. Future capacity and sampling tuning
remain M9 operational acceptance work.

Verification commands and limitations are recorded in
[issue #60 evidence](../milestone9-observability/verification-milestone9-issue60.md).
