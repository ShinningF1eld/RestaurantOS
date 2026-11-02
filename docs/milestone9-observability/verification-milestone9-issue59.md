# Milestone 9 issue #59 verification

## Follow-up implementation and re-verification — 2026-11-02

The user explicitly authorized fixes after the initial report-only review below.
**F1 and F2 are resolved in the working implementation. All six Issue #59 criteria
are Passed for the API scope exercised here; none remains Failed or wholly
Untested.** The qualifications below still apply. This does not accept all of M9
or constitute hosted-production certification. No commit, publication or GitHub
issue-state change was made.

The comparison base remains `be56a01cc697a4f53d9fea233f2fa5564ca1e607`.
The follow-up changes telemetry resource ownership and metric export, adds
regressions and expands stored-signal acceptance. It does not change business
code, database schemas, endpoint contracts, dependencies or Collector policy from
the initially reviewed implementation. Pre-existing edits and deletions remain
preserved. Python 3.12.13 and the existing hash-locked environment were used.
The follow-up implementation snapshot (report excluded), using the sorted-map
hashing procedure recorded below, is
`sha256:545ed3167819dc95810183e7c518751a5a2b7e1cc39ce6c57a3ae8e33e30d8b8`.

### Corrections and independent reproduction results

| Finding | Implemented correction | Fresh evidence |
|---|---|---|
| F1 — cumulative metric export loss | `BudgetedMetricExporter` in `backend/app/core/telemetry.py:91` uses the installed SDK's supported 16-datapoint splitting. The 65,536-byte cap is retained. A shared per-collection send deadline reduces each HTTP timeout and prevents new sends after expiry; every subsequent collection receives a fresh budget. No custom protobuf batching was introduced. | Replaying the original **228-group, 134,619-byte** probe now returns **SUCCESS** for both first and idle exports: **31 batches each**, largest **7,247 bytes**, at most **16 datapoints**. Actual OTLP HTTP tests decode and check every bounded body. The real stack stores all 228 capacity combinations after quiet re-export, with the selected counter still **1**. |
| F2 — leaked readers during partial initialization | `Telemetry._own` (`backend/app/core/telemetry.py:242`) retains each returned exporter/processor/reader until its successfully constructed SDK parent adopts it. Constructor failure transfers partial resources to asynchronous lifecycle retirement. `_retire` (`:316`) retains the runtime and fences replacement until successful cleanup; failed cleanup keeps monitoring disabled rather than allocating more workers. | Repeating the original metric-provider construction fault twice creates two actual SDK readers over time but leaves **0 extra live readers after each cleanup**, zero owners, retirement complete and no retained runtime. New tests inject failures at trace processor, log processor, metric reader, meter provider and instrument construction, then verify healthy restart. Controlled delayed cleanup verifies nonblocking startup and retry fencing; failed cleanup keeps the fence. |

Evidence: `test-results/issue59-fixes-independent-probes.log`,
`backend/tests/unit/test_telemetry_recovery.py`, and
`backend/tests/integration/test_http_observability.py`.
The independent probes use the actual SDK/encoder and recording transport, without
a database or network. The stored acceptance below supplies separate real-network
and backend-storage evidence. The capacity fixture spans registered business
operations and six approved outcomes; it is not a throughput benchmark or a claim
that each status is reachable on every operation.

The shared metric deadline limits new transfers, not hard cancellation of a Python
thread. An in-progress HTTP attempt and SDK retry backoff remain individually
bounded and may finish after that deadline. Application shutdown retains its
configured bounded wait. Retirement fencing prevents further allocations while
cleanup is unfinished or has failed. A single oversized datapoint still drops
safely; telemetry remains disposable and cumulative partial exports can be stale.
Freshness must be checked rather than interpreting missing samples as zero.

### Current criteria and coverage

AC numbers refer to the six acceptance bullets in
[Issue #59](https://github.com/ShinningF1eld/RestaurantOS/issues/59), in order.

| Criterion | Status | Evidence and limits |
|---|---|---|
| AC1 — bounded process pipeline, disabled/outage startup and shutdown | **Passed** | Existing disabled, overlapping/sequential lifespan and outage tests plus the new real-SDK partial-allocation cleanup/retry tests. API startup fails open; shutdown waits only the configured budget. Permanent cleanup failure intentionally leaves monitoring fenced for the process lifetime. |
| AC2 — safe request metrics, histogram quantiles and in-flight accounting | **Passed** | Fresh unit/integration checks cover normalized dynamic and unknown routes, bounded outcomes, actual middleware statuses, cancellation/exception release and histogram buckets. Actual Prometheus queries verify finite P50/P95/P99, zero final in-flight values, **242 request series including all 228 capacity groups**, and quiet cumulative re-export without inflated counters. F1 regression now passes. |
| AC3 — request/log/span correlation and trusted trace context | **Passed** | Fresh unit coverage and actual stored request/log/span linkage; trusted W3C continuation, malformed/untrusted roots and ignored baggage/tracestate. Trace context provides no authentication authority; full API regressions pass. Later frontend/infrastructure/worker tracing remains excluded. |
| AC4 — source and Collector privacy with stored-signal inspection | **Passed** | Actual FastAPI/PostgreSQL canary workload and hostile spoofed-service probe query Prometheus, Loki and Tempo. Canary values and disallowed resource/scope/schema, exception, SQL, body and raw-path data are absent. Loki index policy remains bounded. This covers exercised sources, not arbitrary future instrumentation. |
| AC5 — disposable export, safe local diagnostics and business invariants | **Passed** | Fresh PostgreSQL tests cover Collector absence, mid-workload outage, slow consumption/queue overflow and repeated rejection while preserving committed orders, one stock consumption and audit/replay semantics. Local JSON/no duplicate receiver behavior remains intact. F2 cleanup and F1 recovery now have explicit regressions. |
| AC6 — contracts, configuration, dependencies and documentation | **Passed** | Fresh full backend integration, static/baseline and image gates, plus private-network telemetry smoke from the rebuilt image. No schema/business-route changes. Existing source/lock consistency remains checked; follow-up changes require no dependency updates. Separate frontend/browser/migration gates and remote CI are not claimed. |

### Fresh follow-up executions

Commands run from the repository root; `P` is
`backend/.venv-observability/Scripts/python.exe` (Python 3.12.13).
`--no-install` uses the installed locks; it is not fresh clean-install evidence.

| Command / procedure | Actual result / local evidence |
|---|---|
| `P -m pytest tests/unit/test_http_observability.py tests/unit/test_telemetry_recovery.py -q` from `backend/` | **33 passed**, one existing deprecation warning. `test-results/issue59-fixes-focused-unit.log`. |
| Disposable `services(False)` / guarded `disposable_database`, migrate only the allocated database, then `P -m pytest tests/integration/test_http_observability.py -q` from `backend/` | **8 passed, 1 skipped**, 31 existing deprecation warnings; owned cleanup completed. Explicit stored-workload skip is exercised by the separate acceptance runner. `test-results/issue59-fixes-focused-integration.log`. |
| `P scripts/validate.py --gate backend-unit --gate backend-static --gate baseline --no-install` | **485 unit tests passed**, one existing warning; Ruff lint/format, mypy and baseline passed. `test-results/issue59-fixes-fast.log`. |
| `P scripts/validate.py --gate backend-integration --gate image --no-install` | **355 passed, 1 skipped**, 1,004 existing deprecation warnings; Alembic reports no new upgrade operations. Backend image secret/nonroot/runtime checks, disposable PostgreSQL connectivity, unchanged schema on startup and health smoke pass; standalone frontend image smoke also passes. `test-results/issue59-fixes-integration-image.log`. |
| `P scripts/check-api-observability.py` | **Passed** real API/PostgreSQL business workload, stored 242 series / 228 capacity groups after quiet export, P50/P95/P99, zero in-flight, exact request/log/span linkage, absent canaries and hostile Collector probe; owned teardown passed. `test-results/issue59-fixes-storage.log`. |
| `P scripts/check-api-observability.py --container-smoke` | **Passed** rebuilt production API image exporting privately through `collector:4318` to Prometheus, Loki and Tempo, with correlation and no canary leakage. Owned teardown passed. This health/export check does not perform containerized business writes. `test-results/issue59-fixes-container.log`. |
| Original F1/F2 probes replayed against the corrected implementation | **Passed**, measurements above. `test-results/issue59-fixes-independent-probes.log`. |
| `P scripts/validate.py --gate baseline --no-install` after documentation/report updates | **Passed**, including the non-mutating secret scan. `test-results/issue59-fixes-final-baseline.log`. |
| `git diff --check`; `docker ps -a --format '{{.Names}}'` | Diff check passed (existing CRLF normalization notices only); **no containers remained** after verification. |

The follow-up does not change Collector configuration. The pinned parser and #58
synthetic host/container results retained below therefore remain relevant prior
evidence; they were not rerun as a full #58 fault/retention/resource matrix.
All service-backed runs use owned disposable PostgreSQL/Redis and monitoring
projects, never the developer application database. Schema/API changes: none.

### Follow-up limits

Full backend and image checks are now fresh, superseding the initial review's
retained-only qualification for those gates. Browser/SSR, separate frontend
unit/static/build and clean/legacy migration gates, remote CI, hosted deployment,
long-duration destination failures and quantitative overhead/resource trials
remain untested in this follow-up. The image gate's frontend smoke is narrower
than those frontend gates. No new actionable finding was identified in the
focused re-review; this is not proof that every possible SDK or transport failure
has been injected. Raw logs are ignored local artifacts, not a committed bundle.

## Publication CI follow-up

After the user authorized commit/push/merge, commit `8e45eeb` was pushed in
[PR #70](https://github.com/ShinningF1eld/RestaurantOS/pull/70).
The first remote CI execution passed eight gates and the 29-test Chromium suite,
then failed the separate gateway rehearsal's controlled-identity fixture.
Its test-only `gateway_test_probe` logger relied on interpolated raw messages
that the new production formatter intentionally suppresses. The harness is updated
to emit its existing fixed marker directly to stdout, exclusively from the
disposable mounted probe: an allowlisted A/B/C label and two boolean checks.
No addresses, credentials or arbitrary header values are emitted. All existing
identity, forged-header and quota assertions remain unchanged; the production
formatter and its privacy policy remain unchanged.

Ruff lint and format checks pass for the runner. A new CI execution must verify
the corrected harness before merging. This section records the discovery and fix;
GitHub's current PR checks are the source for subsequent remote CI/merge status.
The snapshot fingerprint above predates this additional test-harness change.

## Initial review — historical findings and evidence

Everything below records the original report-only review **before the fixes**.
Its failed statuses, old line locations, unchanged-file statement and next actions
are historical and are superseded by the follow-up above.

Reviewed: 2026-11-02 (Asia/Bangkok).

Sources: [Issue #59](https://github.com/ShinningF1eld/RestaurantOS/issues/59),
[observability design revision 1](milestone-9-observability-design.md),
[T2 acceptance criteria](milestone-9-observability-task.md), root `AGENTS.md`,
[API telemetry contract](../api/observability.md), and the monitoring configuration,
runbook and testing guide. The review follows the `review-verify` skill.

Revision: `be56a01cc697a4f53d9fea233f2fa5564ca1e607` plus the uncommitted working
implementation. This is a review of current files, not a published PR head.
HEAD provides comparison context; it does not contain the new telemetry modules.
The pre-existing request-normalization edits and deletion of the two #58 documents
(`implementation-issue58.md`, `recheck-milestone9-issue58.md`) were preserved and
are not attributed to this review. No implementation files were changed.

Environment: Windows/PowerShell, Python 3.12.13 in
`backend/.venv-observability`, locked OpenTelemetry Python SDK/exporter 1.45.1,
and local Linux Docker containers. Service-backed checks use owned disposable
PostgreSQL/Redis projects and guarded unique `_test` databases. No developer
application database was selected, migrated or faulted.

### Initial review result — superseded

**Issue #59 should remain open pending two P2 corrections.** Small-workload
telemetry, correlation, privacy filtering and the exercised outage/business paths
pass. Additional review probes demonstrate sustained metric-export loss at a
larger approved label set and leaked periodic-reader threads after partial SDK
initialization failure. Green existing gates do not cover those two cases.

Of the six issue criteria, **3 are Passed, 3 are Failed, and 0 are wholly Untested**.
The failed criteria contain passing sub-behaviors documented below. This is not
full M9 acceptance or a hosted-production readiness claim.

### Initial criteria and coverage — superseded

AC numbers below refer to the six acceptance bullets in Issue #59, in order.
Design references apply only to the API slice owned by this issue.

| Criterion | Status | Evidence and demonstrated behavior | Remaining gap |
|---|---|---|---|
| AC1: one bounded configurable process pipeline; disabled/outage startup and bounded shutdown (R5) | **Failed** | Fresh unit and focused integration checks pass disabled operation, unavailable Collector, normal overlapping/sequential lifespans and bounded application shutdown. SDK exporters run outside the business command path. | F2: failure after periodic-reader creation leaves its thread alive; repeated initialization attempts accumulate readers outside lifecycle ownership. |
| AC2: request rate/status/outcomes, seconds histograms and in-flight counts with bounded route/method dimensions (R3/R5) | **Failed** | Fresh SDK tests cover normalized dynamic routes, unmatched paths, client/conflict/rate-limit/server categories, cancellation and post-header exceptions. Fresh stored-data checks find 21 request series, finite P50/P95/P99 values and zero final in-flight counts. | F1: the cumulative metric snapshot is exported as one request; a larger approved label set exceeds 64 KiB and stops exporting even with a healthy transport. |
| AC3: request/log/span correlation; trusted valid context and safe malformed context (API portion of R3) | **Passed** | Fresh unit tests and actual stored API data demonstrate request-ID preservation, matching trace/span IDs, trusted W3C continuation, fresh roots for malformed/untrusted context, and no baggage/tracestate extraction. Authentication remains independent of trace context by inspection and retained full API regressions. | No Next.js, database/Redis or durable worker trace claim; those belong to later issues. |
| AC4: source/Collector privacy, framework/validation/unhandled canaries and actual exported-signal inspection (R5) | **Passed** | Fresh unit tests and the real API/Collector/PostgreSQL workflow exclude the seeded canary from queried metrics, logs and traces. A separate spoofed-service probe checks resource/scope/schema metadata, log body/event/severity, span events/status/tracestate, SQL attributes, unknown metric names and raw-path dimensions. Loki index-series inspection admits only `service_name`; request/trace/span IDs remain metadata. | This establishes the exercised sources and canaries, not a guarantee for future instrumentation or arbitrary future application logging call sites. |
| AC5: local structured diagnostics, no duplicate ingestion, bounded export/flush and preserved committed order/audit behavior (R5) | **Failed** | Fresh focused PostgreSQL tests pass pre-start absence, mid-workload 503 rejection, slow replies/queue overflow and repeated export rejection; committed order state, one stock consumption and audit/replay rules hold. Local diagnostics remain available and there is no stdout/filelog receiver duplicating OTLP logs. Application shutdown waits only its configured budget. | F2 violates complete resource ownership/bounded repeated-startup cleanup. The caller's shutdown wait is bounded; it is not evidence that every partial initialization resource has been retired. |
| AC6: route/error/session/CSRF/health contracts, bounded settings, source/hashed locks and documentation | **Passed** | Fresh static/baseline and settings tests pass. Retained full integration and image checks pass compatibility and runtime packaging; no migration/business endpoint changes are present. Existing dependency pins are retained. Units, categories, configuration, retention/loss behavior and SDK limits are documented. | The separate `migrations`, browser, frontend gates and remote CI were not rerun for this report. They are not represented as passing here. |

### Initial findings — resolved above

### F1 — P2: cumulative metrics outgrow the exporter limit and stop recovering

Location: `backend/app/core/telemetry.py:72` and `:125–130`.

Trigger: a process accumulates enough approved route/method/status/outcome
combinations for its cumulative metrics to exceed the 65,536-byte request cap.
The metric exporter is created without `max_export_batch_size`, so SDK 1.45.1
encodes the entire snapshot as one batch and rejects it before transport.

Expected: healthy collection continues to export the bounded HTTP instruments as
the registered API is exercised. Payload limits should not permanently disable
all four instruments after ordinary label-set growth.

Actual: a small control snapshot exports successfully. A larger cumulative
snapshot fails locally, and a subsequent idle collection fails again because the
same label sets remain in cumulative state. The Collector receives neither
snapshot. Requests still succeed; this is an observability failure, not a
business-state corruption or privacy finding. The API contract documents oversized
drops, but does not provide recovery from this lasting healthy-transport condition.

Review reproduction (real SDK, in-process recording transport, no database/network):

1. Construct the production `Telemetry` object, substituting only an
   `InMemoryMetricReader` for periodic scheduling and a recording HTTP session
   that returns 200. Retain the actual `OTLPMetricExporter` and production options.
2. Record one request/duration/in-flight/freshness observation. Its **877-byte**
   encoded snapshot returns `SUCCESS` and invokes the transport once.
3. Obtain **38 business route/method operations** from the current OpenAPI schema;
   record the six approved status/outcome pairs 200/success, 401/authentication,
   403/forbidden, 404/not_found, 422/validation and 500/server_error for each.
4. The **228 distinct combinations** produce **134,619 bytes**. Both the first
   export and an idle re-export return `FAILURE`; **zero additional transport
   calls** occur. `max_export_batch_size` is `None`.

This is a label-capacity probe, not an HTTP load benchmark or a claim that every
listed status is reachable on every operation. All routes/methods are registered
and all dimensions are admitted by the application policy; no raw IDs or unknown
labels were needed to exceed the cap.

Evidence: `test-results/issue59-review-metric-control.log`; confirmed against the
installed SDK's metric exporter size check and cumulative reader behavior.
Attribution: new telemetry setup; high confidence.

Suggested correction: use the installed SDK exporter's supported metric batching
option, with a safe per-batch size and bounded whole-export/shutdown work. Retain
the receiver/body limits. Add a regression that grows realistic approved label
coverage and verifies continuing stored metrics, including a later quiet interval.
No configuration or implementation was changed to obtain a pass in this review.

### F2 — P2: partial metric-provider initialization leaks periodic readers

Location: `backend/app/core/telemetry.py:125–144`, `:158–167` and `:193–205`.

Trigger: `MeterProvider` construction raises after
`PeriodicExportingMetricReader` has been created. The SDK reader starts its daemon
thread immediately, but ownership is recorded only after the provider constructor
returns. Exception cleanup shuts down the already-registered trace/log providers
and never shuts down this reader/exporter.

Expected: a failed initialization retires every resource created so far, and
retrying cannot accumulate orphan exporter/reader workers.

Actual: initialization fails open as intended, returning no pipeline, but each
retry adds another live `OtelPeriodicExportingMetricReader` thread. The lifecycle
has zero owners and its retirement event remains set, allowing further attempts.
This is a partial local SDK-construction fault; ordinary Collector unavailability
does not itself trigger this fault and passes the existing outage tests.

Review reproduction (fault injection, actual SDK readers, no database/network):

1. Track real periodic-reader instances; inject a `RuntimeError` only into the
   subsequent metric-provider constructor.
2. Call a fresh lifecycle manager's `acquire(settings)` twice with monitoring
   enabled and a 30-second collection interval.
3. Both calls return `None`. Extra live reader counts are **1 after the first
   failure and 2 after the second**, with `owners == 0` and retirement set.
4. Explicitly shut down the tracked readers in probe cleanup; the extra-thread
   count returns to **0**.

Evidence: `test-results/issue59-review-probes.log`; SDK source confirms immediate
reader-thread startup. The existing initialization-failure unit test replaces
the entire `Telemetry` constructor and therefore cannot detect partial allocation.
Attribution: new startup ownership/cleanup code; high confidence for this injected
failure boundary. The review did not observe this fault during normal startup.

Suggested correction: own and close readers/exporters as soon as they are created,
including resources not yet attached to a successfully constructed provider.
Keep cleanup bounded and preserve the retirement fence until cleanup completes.
Add failure injection at each partial-construction boundary and assert that
repeated lifespans leave no additional worker threads or open exporters.

### Initial review executions

Commands below run from the repository root unless another directory is stated.
`P` means `backend/.venv-observability/Scripts/python.exe` (Python 3.12.13).
All review runs use the existing locked environment; `--no-install` is explicitly
partial installation evidence, not a fresh clean-install or milestone gate claim.

| Check | Evidence type / command or procedure | Result |
|---|---|---|
| Fresh unit/static/baseline gates | `P scripts/validate.py --gate backend-unit --gate backend-static --gate baseline --no-install` | Passed: **475 unit tests**, Ruff lint/format, mypy and baseline. One existing Starlette/httpx deprecation warning. Output: `test-results/issue59-review-gates.log`. |
| Fresh stored-signal acceptance | `P scripts/check-api-observability.py` | Passed actual FastAPI/PostgreSQL workload, stored Prometheus/Loki/Tempo checks, request/log/span linkage, histogram quantiles, privacy probes and owned cleanup. Output: `test-results/issue59-review-storage.log`. |
| Fresh focused failure/lifecycle integration | Existing `services(False)` and `disposable_database(prefix='restaurantos_review59', ...)`; migrate only that allocated database; from `backend/`, `P -m pytest tests/integration/test_http_observability.py -q` | **7 passed, 1 skipped**, 31 existing deprecation warnings; cleanup succeeded. The skipped stored-workload case passed through the separate runner above. Output: `test-results/issue59-review-faults.log`. |
| Metric growth and idle recovery | Read-only in-process procedure under F1, actual SDK exporter/encoder with a 200 recording session | **Failed** after growth, with passing small control. Output: `test-results/issue59-review-metric-control.log`. |
| Partial-construction cleanup | Read-only in-process procedure under F2, real SDK reader threads and injected provider-construction error | **Failed** ownership assertion; all probe-created readers explicitly cleaned. Output: `test-results/issue59-review-probes.log`. |
| Working-tree preservation / cleanup | SHA-256 comparison of all initially modified/untracked files, excluding this report; `docker ps -a` | Implementation snapshot unchanged; no Docker containers remained after review checks. |

The focused integration command was launched through the existing disposable
helpers using `database.environment(environment)` and `python -m alembic upgrade
head` in `backend/`; no ambient developer database URL was used. Manual probes
were supplied to Python on stdin; no test modules or source files were written.

### Retained implementation-phase evidence, not rerun as full gates in this review

| Earlier command / procedure | Retained result and qualification |
|---|---|
| `P scripts/validate.py --gate backend-unit --gate backend-static --gate baseline --gate backend-integration --gate image --no-install` | `test-results/issue59-complete-required-gates.log`: 475 unit tests, **354 integration tests passed**, one explicit stored-workload skip, static/baseline/image checks passed, and Alembic reported no new upgrade operations. These are prior executions from this chat, not fresh review executions or remote CI. |
| `P scripts/check-api-observability.py --container-smoke` | `test-results/issue59-final-container.log`: production API image exported over private `collector:4318` to all three stores; canary absent; cleanup passed. This health/export smoke does not exercise database business writes inside the container. |
| `P scripts/check-monitoring-config.py` | `test-results/issue59-final-parsers.log`: four pinned monitoring parsers passed. |
| `P scripts/check-monitoring.py --mode host --report test-results/issue59-synthetic-host.json` and the same command with `--mode container --report test-results/issue59-synthetic-container.json` | Both retained #58 synthetic contracts passed and recorded `cleanup_verified: true`. No claim of rerunning the full #58 retention/resource/destination-outage matrix in this review. |

The earlier implementation attempts include corrected fixture assumptions,
minute-boundary timing, scanner false positives, an avoided transitive dependency
upgrade, and runs interrupted for the user's pause or lock correction. Their
outputs remain separate in ignored `test-results/`; they are not substituted for
the final passing runs. F1/F2 are additional findings that those final runs missed.

### Initial snapshot, limits and next actions — historical

The review's pre/post implementation snapshot fingerprint is
`sha256:29db344f250ac9058a6fe37a77dac04f04e94a79546e67b64f4ae6c688a04a06`.
It hashes UTF-8 JSON of the sorted map of initially modified/untracked repository
paths to their file SHA-256 values (or null for deleted files), with compact JSON
separators and this report excluded. Before writing the report, the changed-file
comparison was empty. Raw check outputs are ignored local artifacts, not committed
evidence bundles; preserve them separately if long-term reproducibility is needed.

Full backend integration and image gates were inspected as retained evidence,
not rerun in full for this report. Browser/SSR journeys, the remaining frontend
gates, separate clean/legacy migration gates, remote CI, long-duration destination
faults, quantitative overhead/resource trials and hosted deployment are **Untested
in this review**. No schema changes require a new migration for this issue.
Next.js tracing, SQL/Redis instrumentation, outbox/worker propagation, business
metrics and dashboards remain #60–#64 work; this report does not accept the whole
R3/R5/R12 milestone scope or close M9.

Fix F1 and F2 in follow-up implementation work, add regressions for both
reproductions, then rerun the affected required gates and actual stored-signal
checks. No code fixes, commits, issue updates, GitHub comments, publication or
changes to the pre-existing deletions were performed as part of this review.
