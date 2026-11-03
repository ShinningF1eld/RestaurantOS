# Issue #60 — Next.js server request tracing

Date: 2026-11-02 (Asia/Bangkok). Scope: current M9 observability T3; historical
deployment M9 remains current M15. This is local issue evidence, not full M9 or
hosted production acceptance. Implementation verification preceded the user's
subsequent commit/push authorization. No application migration or developer
database operation was requested or performed.

## Implementation and contracts

The working tree was clean before inspection. Root/frontend instructions,
README/current-state, the observability design R3/R5/R9/S2, live GitHub issues
#58/#59/#60, installed Next.js 16.3.7 instrumentation/OpenTelemetry/runtime/startup
and deployment docs, SSR/renewal/client flows, test harnesses, standalone packaging
and Collector policies were inspected before implementation.

The Node-only startup hook initializes one tracing provider, async context,
validated traceparent-only extraction and bounded OTLP/HTTP export. Next's own
server/render spans remain; one explicit existing API-client CLIENT span carries
validated context to the configured API origin, with overlapping Next fetch spans
disabled. Default global injection is empty, so unrelated destinations receive
no ambient trace context. Cookie, no-store, redirect rejection, 401 renewal,
return-path, CSRF and tenancy behavior are preserved.

Before queueing, framework/application spans are replaced with fixed-name,
allowlisted snapshots without raw URLs, query values, exception messages/stacks,
events, links, baggage, vendor state, bodies or rendered HTML. Frontend remote
logging is not enabled. Collector has an independent frontend policy. Settings,
loss/shutdown boundaries, service identity, dependency decisions and host/container
configuration are in the [runtime contract](../api/frontend-observability.md).
No Dockerfile change is necessary: Next standalone tracing includes the runtime
dependencies, verified by real image execution. Next.js remains pinned at 16.3.7.

| Issue #60 criterion | Evidence |
|---|---|
| Installed docs, supported entry point/runtime guard, no browser inclusion | Inspection above; `instrumentation.ts`; Node registration tests; production image browser-marker check |
| Authenticated SSR/API trace in both modes | Real Tempo trace IDs, distinct span IDs and full ancestry assertions in both focused runs |
| Access-cookie/no-store/redirect/401 behavior | Node API-client test, focused SSR response assertions, all Chromium renewal and HTTPS tenant journeys |
| Validated trusted-destination propagation only | Strict traceparent tests, origin/userinfo rejection, empty ambient injection and real malformed/missing-context SSR |
| Safe exported signals and outage independence | Actual raw host OTLP before Collector plus stored healthy/error/body canaries; cold outage startup and private/foreign requests in both modes |
| Browser boundary, locked dependencies, standalone image | Runtime contract explicitly defers browser timings; clean npm ci; actual nonroot production-image SSR/Collector run |

## Commands and results

All commands are from the repository root unless noted. Windows used Python
3.13.15 in the existing test venv, Node 24.14.1, Docker Desktop Linux/AMD64;
supported CI Python remains 3.12. Commands requiring Docker/local HTTP used the
approved unrestricted test execution context after sandbox EACCES failures.

| Command | Result |
|---|---|
| `npm ci --no-audit --no-fund` in `frontend/` | Passed, 472 packages from the updated tracked lock |
| `backend/.venv/Scripts/python.exe scripts/validate.py --gate frontend-tests --gate frontend-static --gate frontend-build --no-install` | Passed; 10 client, 19 component, 7 Node server tests; ESLint/Prettier/typecheck and production build |
| `$env:MONITORING_ENABLED='true'; $env:MONITORING_ENDPOINT='http://127.0.0.1:1'; backend/.venv/Scripts/python.exe scripts/validate.py --gate browser --no-install` | Passed; 29 Chromium journeys, 15 HTTPS gateway checks, both intentional-failure cleanup probes; auth browser traces off |
| `backend/.venv/Scripts/python.exe scripts/validate.py --gate image --no-install` | Passed both nonroot Linux/AMD64 runtime images; standalone assets and browser telemetry exclusion |
| `backend/.venv/Scripts/python.exe scripts/check-frontend-observability.py --mode host` | Passed authenticated real SSR/API/Tempo ancestry, raw source healthy/exception/body privacy, tenant/renewal/outage checks and cleanup |
| `backend/.venv/Scripts/python.exe scripts/check-frontend-observability.py --mode container` | Passed final standalone/API images, internal DNS, same-trace ancestry, healthy/exception/body privacy, tenant/renewal/outage checks; graceful stops 0.378s healthy / 4.097s after outage, exit 143, no OOM, owned cleanup |
| `backend/.venv/Scripts/python.exe scripts/check-monitoring-config.py` | Passed all four locked native parsers, including Collector frontend policy |
| `backend/.venv/Scripts/python.exe scripts/validate.py --gate backend-static --gate backend-unit --no-install` | Passed Ruff/format/mypy (167 app sources), harness static checks and 486 pure tests |
| `backend/.venv/Scripts/python.exe scripts/validate.py --gate baseline --no-install` | Passed dependency consistency, candidate secret scan and Compose models |
| `git diff --check` | Passed |
| `npm audit --json --omit=dev` in `frontend/` | Nonzero: unchanged Next.js 16.3.7 has critical advisories; no added OpenTelemetry dependency reported |

The focused harness reuses existing disposable monitoring/service/database owners,
seeds two private tenants, and inspects actual Tempo traces for unique span IDs,
same trace ID and API -> CLIENT -> Next server ancestry. Host mode also captures
actual source OTLP in memory before Collector filtering. It exercises private
rendered content and synthetic cookies/headers/query/body/path values, a real
framework exception, malformed/missing context, 401 renewal redirects without
Set-Cookie, foreign-tenant reads and Collector-absent cold startup/requests/exit.
Container mode runs the actual nonroot standalone/API images using private API
and Collector DNS with the exact frontend peer configured in FastAPI.

Node tests additionally inspect actual OTLP wire serialization for exception,
resource/scope and URL canaries; validate trust and malformed traceparent behavior;
prove single/disabled registration, unchanged cookie/cache/redirect/401 behavior,
and actual HTTP timeout/maximum retry behavior against slow/503 receivers. The
SDK can emit a harmless negative-timeout warning at the final synthetic retry;
the asserted elapsed-time and at-most-six-attempt bounds pass. The image checker
rejects server telemetry markers in browser assets.

Container shutdown uses an explicit six-second grace (asserted under seven seconds
including CLI overhead), closes completed test clients and rejects forced-kill
exit codes. A stricter whole-process three-second probe did not pass after the
outage workload. The telemetry setting is a diagnostic deadline, not a replacement
for Next's HTTP drain; the final normal exit at 4.097 seconds is the measured
boundary, not a claim of three-second whole-process shutdown. Logical API reads
can outnumber wire calls because Next coalesces identical fetches; tests preserve
that behavior and assert ancestry for each actual API span instead of forcing new
network calls to make span counts match.

## Corrections and limits

Early runs exposed test setup issues, not passing acceptance: local npm-ci/build
overlap hit a Windows native-module lock and interrupted the host dependency tree;
a subsequent clean npm ci and full frontend rerun passed. Missing locked Chromium
was installed before rerunning the full browser gate. Internal-only Docker bridges
cannot serve published host test ports: the harness now attaches the existing
host-ingress bridge while API/Collector calls use the private bridge. The synthetic
source receiver now handles bounded chunked OTLP uploads. Query text echoed from
the caller is separate from private tenant data; isolation checks use an unadorned
foreign URL. The exception fixture uses an invalid menu under a valid restaurant,
rather than a deliberately handled not-found layout. Synthetic scanner findings
are explicitly inline-allowlisted; detector policy is unchanged.

Shared validation selections are partial (`--no-install`); the explicit clean
`npm ci` separately establishes npm lock reproducibility. Backend integration and
migration gates were not selected: no backend behavior or schema changes. Real
migrated disposable PostgreSQL is used by browser and SSR integration. No remote
CI, ARM runtime, deployment, sustained capacity, sampling optimization or full
milestone acceptance is claimed. Telemetry is disposable and may be lost at
shutdown/outage; no delivery guarantee is introduced. Framework security updates
remain separate work: [the runtime audit's critical advisory](https://github.com/advisories/GHSA-2464-fhr4-w9xw)
affects the existing pin, which this issue deliberately does not upgrade.
