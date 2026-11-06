# Milestone 9 issue #62 verification

## Follow-up implementation and re-verification — 2026-11-06

The user authorized the F1 correction and a new comparison against all Issue #62
criteria. **F1 is resolved for the documented bounded-slot configuration. All six
published criteria are Passed within the local scope below.** The original
report and reproduction remain below as historical evidence; their Failed AC5
status is superseded by this section. No issue status/checkbox, commit, push or PR
was changed. No developer application database was migrated or faulted.

### Correction and compatibility

`Settings.monitoring_worker_slot` adds optional `MONITORING_WORKER_SLOT`, validated
in **0–31**. `WorkerMetrics` adds the bounded `worker_slot` dimension only to
process-local counters/histograms. Shared worker SQL/Redis/pool diagnostics use
the same slot; Collector worker/infrastructure admission validates the range and
preserves the discriminator. API instrumentation remains unchanged.

Each concurrent worker targeting one Collector must receive a distinct slot.
Slots are explicit operator configuration, not arbitrary worker UUIDs or business
identifiers. Stop the previous owner before reusing a slot. Duplicate explicit
assignments are invalid and are not automatically detected; no distributed slot
allocator, database lease, new service or additional migration was introduced.
Counters reset normally when a retired slot is reused. Rate each slot before
summing rates across slots.

An unassigned worker does **not** silently fall back to a shared process series:
its traces, local diagnostics and durable backlog/recent-receipt gauges continue,
but process-local event/SQL/Redis/pool metrics are suppressed with a safe startup
warning. This is an intentional observability configuration change: existing
worker monitoring setups need an explicit slot to retain process-local metrics.
Durable database snapshot gauges never gain a slot label and do not multiply
when another worker reports the same retained facts.

The new native Collector regression uses the actual pinned image, actual SDK
providers/OTLP HTTP, and current worker plus infrastructure policies. It verifies:

| Procedure | Result |
|---|---|
| Producers in slots 0/1 record 5/9 completed operations | Two independent series, 5 and 9; service observation sum 14 |
| Slot 0 quietly re-exports its cumulative snapshot | Both series stay 5/9; no spurious reset or loss of slot 1 |
| Actual native duration histogram and SQL counter | Per-slot histogram counts and SQL slow counters are 5/9 |
| Two providers report durable queued depth 12 | One unslotted gauge at 12, not a fabricated backlog of 24 |
| Retire slot 0 and start its replacement at count 1 | Slot 0 resets to 1; slot 1 remains 9 through its next export |
| Unassigned provider records 17 would-be operations | No additional process series; existing assigned streams stay 1/9 |

The native backlog name remains `restaurantos_worker_deliveries_ratio` with SDK
unit `1`; operation counters and duration histograms use the existing documented
Prometheus suffixes. The regression is tracked in
`backend/tests/integration/test_event_metric_export.py`; its owned Collector
helper is `backend/tests/support/worker_collector.py`. It runs in the ordinary
`backend-integration` gate rather than relying only on a temporary manual probe.

No business/event payload, operator command, receipt, retry policy, claim fencing,
audit/stock transaction or financial projection logic changed. The prior additive
migration `d4e9f2a63b85` remains the single head; this correction adds no revision
or dependency. Slot settings, reset/aggregation behavior, unassigned behavior and
operational commands are documented in the event/API/infrastructure contracts,
tracked env example and worker runbook.

### Current acceptance mapping

AC numbers still refer to the six live GitHub Issue #62 bullets, re-read during
this follow-up. This is issue-slice acceptance, not all M9 or hosted certification.

| Criterion | Status | Fresh evidence and boundaries |
|---|---|---|
| AC1 — safe optional context, atomic persistence, no sensitive trace metadata or transaction export | **Passed** | Strict validation/omission and SDK tests pass. Rollback coverage now holds a recording span open, asserts the flushed row has non-NULL context, then aborts and proves the event is absent. Source inspection confirms caller-owned transaction/flush only and no export call in append. V1 payloads and independent correlation remain unchanged. |
| AC2 — preservation, NULL history, one head/drift and compatible downgrade | **Passed** | Fresh standalone migrations gate passes clean/seeded upgrade, business/history preservation, metadata/index downgrade/re-upgrade, backup/restore and drift checks. New integration test downgrades only its disposable DB to the pre-column schema, inserts an event/delivery without the column, upgrades, asserts NULL and completes it with the real production worker. No fabricated context. Current ORM code runs only after the schema is restored. |
| AC3 — linked publication and actual attempts with independent lifetimes and safe identities | **Passed** | Source OTLP now asserts both origin trace ID and span ID, root worker lifecycles, remote-context bits and empty link vendor state/attributes. New real-PG publication branch tests inspect `published`, `claim_lost`, `transport_failure`, `observation_failure`, duration-capable spans and unchanged pending/attempt state. SDK link-context tests verify full preserved W3C flags; pinned wire-encoder limitation below is explicit. |
| AC4 — restart/legacy/retry/replay/duplicate distinction and correct effects/totals | **Passed** | Authenticated real API calls generate inventory/menu/order events, the first worker is killed after a deterministic claim barrier, and restarted production processing exports exact linked identities for analytics, alerts and notification_sink. Pre-column legacy processing, failed/retried/terminal/replayed attempts, duplicate ACK/no additional execution span, diagnostic deduplication and completed-sales reconciliation pass. The full analytics suite freshly covers effect rollback, authorized replay, duplicate receipt and reconciliation without inflated completed counts. |
| AC5 — durable backlog/progress, meaningful states and reliable operational metrics | **Passed** | F1's interleaved healthy-producer collision is covered by the native regression above. State/oldest-age tests cover queued, in-flight, delayed retry, terminal and expired-lease recovery. A real exclusive table lock triggers the bounded aggregate SQL timeout and a subsequent query succeeds without a stale session. A pure metrics-loop test proves failed collection leaves the prior collection time unchanged, followed by successful refresh; cadence remains 15s. Source metrics have bounded labels, fixed units and documented durability/reset/freshness limits. Requires valid distinct slot configuration for process streams. |
| AC6 — outage-independent work/ACK, bounded lifecycle/loss diagnostics and expired contexts | **Passed** | Fresh production worker tests process and reconcile receipts/sales with a closed Collector port and a rejecting receiver. A deterministic pipe barrier blocks initial telemetry ingestion, then emits 4,096 synthetic SDK spans against a 16-record queue. Local JSON records show queue-full drops while real effects commit; after receiver recovery a new real event completes and exports its linked attempt. Redis group inspection verifies consumption through the latest stream ID and zero pending entries before shutdown. Graceful exit remains bounded. Tempo expiry/context limitations remain documented. |

### Expanded criteria, test gaps and limits rechecked

The following evidence closes the initial report's principal issue-specific gaps:

- **Actual FastAPI origin:** real authenticated HTTP writes precede worker death
  and restart. All three consumer names appear in exported actual execution spans,
  with origin trace/span identities checked against persisted outbox metadata.
  Synthetic ingredient-name canary content stays out of actual OTLP exports and
  final production-worker JSON stderr.
- **Legacy upgrade and rollback:** the same pre-column event is upgraded and
  processed, and non-NULL trace metadata is directly included in rollback proof.
  Migration fixtures separately cover historical delivery/attempt/receipt/replay
  facts and stock/order business preservation.
- **Attempt and publication distinctions:** first/retry/replay IDs, committed
  receipt, terminal failure, duplicate routing and claim ownership retain their
  original semantics. Publication failure telemetry is checked independently of
  successful publication. Redis references still cannot supply authoritative
  trace context; `_start` reloads PostgreSQL context and validates identity fields.
- **Collection failure/freshness:** real PostgreSQL timeout/recovery and an
  isolated metrics-loop failure/success test prove bounded read behavior and no
  false advance of collection freshness. Backlog/receipt queries remain separate
  snapshots, never an atomic financial freshness guarantee. The partial index
  excludes completed delivery history; scan cost still grows with retained
  unfinished/terminal work and is bounded by the statement/task budgets.
- **Outage/drop/recovery:** real worker closed-port, rejection and slow-reader
  scenarios preserve work and ACK handling, and safe local queue-loss diagnostics
  are inspected. The synthetic pressure spans are test wiring outside database
  transactions; they do not fabricate business-effect attempts or add production
  fault endpoints. This is a bounded-queue failure exercise, not a long-duration
  RSS/CPU/throughput capacity benchmark.

**Pinned SDK limit:** installed OpenTelemetry OTLP HTTP **1.45.1** encodes link
trace/span IDs and the `HAS_IS_REMOTE`/`IS_REMOTE` bits, but its installed
`_internal/trace_encoder._encode_links` does not serialize the low W3C flags.
Those flags are verified in persisted `traceparent` and the actual SDK Link
context; wire tests verify what the pinned encoder emits. No private SDK patch,
dependency upgrade, fabricated exported flags or incoming-sampling override was
introduced. Local ALWAYS_ON sampling remains independent of the link's sampling
flags. Retained identifiers cannot reconstruct expired Tempo span data.

Runtime span/canary inspection uses the isolated actual HTTP protobuf collector;
metric stream/rateability checks additionally traverse the pinned native
Collector's real Prometheus exporter. The issue explicitly allows an appropriate
isolated collector; these are not claims of a new stored-Tempo/Grafana journey or
full five-store retention exercise. Existing restricted PostgreSQL/Redis receiver
identities, retention and privacy boundaries are unchanged. R12's broader M9
resource/capacity exercises, quantitative large-history plans/cost, future
business dashboards/alerts, frontend/browser work, remote CI and hosted deployment
remain separate. No required issue criterion is left marked Failed or wholly
Untested within the supported configuration and stated local boundary.

### Fresh follow-up executions

All commands ran from the repository root using the installed committed locks,
Python **3.12.16**, local ARM64 Docker. `--no-install` is partial repository
validation and is not a new clean-install claim. No dependency pins, required CI
check names or enforcement policy changed.

| Exact command / procedure | Actual result / local evidence |
|---|---|
| `backend/.venv/bin/python scripts/validate.py --gate backend-static --gate backend-unit --no-install` | **527 passed** in 7.42s; Ruff lint/format, mypy **171 app sources** and harness static passed. `/tmp/issue62-fix-fast-final.log`. |
| `backend/.venv/bin/python scripts/validate.py --gate backend-integration --no-install` | **373 passed, 1 skipped** in 394.98s; `alembic check` found no new operations; cleanup passed. `/tmp/issue62-fix-integration.log`. The unchanged skip requires `TEST_MONITORING_ENDPOINT` for the separate stored-API acceptance exercise, not these worker tests. |
| `backend/.venv/bin/python scripts/validate.py --gate migrations --no-install` | Clean and seeded legacy paths, unique head, preservation, downgrade guards/metadata round-trip, backup/restore and drift checks passed. `/tmp/issue62-fix-migrations-final.log`. |
| `backend/.venv/bin/python scripts/validate.py --gate baseline --gate image --no-install` | Compose/dependency/secret checks and both nonroot production images/build/runtime smoke tests passed. Startup did not migrate the disposable database. `/tmp/issue62-fix-baseline-image.log`. |
| `backend/.venv/bin/python scripts/validate.py --gate baseline --no-install` | Final report/docs Compose, dependency and secret-baseline checks passed. `/tmp/issue62-fix-baseline-final.log`. |
| `backend/.venv/bin/python scripts/check-monitoring-config.py` | All four pinned Collector/Prometheus/Loki/Tempo native parsers passed. `/tmp/issue62-fix-parser.log`. |
| `backend/.venv/bin/python /tmp/issue62-final-focused.py` | **16 passed** in 26.20s, including latest explicit stream-consumption/ACK assertions. `/tmp/issue62-fix-focused.log`. The temporary runner uses repository `services(False)` and guarded `disposable_database`, migrates only its allocated test DB, then runs the two tracked event telemetry/native-export modules. |

The complete integration run includes the original claim/stock/order/audit/auth/
projection regressions and the new native metrics test. The final focused rerun
also exercises the subsequent test-only explicit ACK helper; runtime code did
not change between those executions. Existing correctness assertions and required gates were preserved; new test
wiring was aligned with the actual API/SDK contracts as described below.

Initial follow-up failures are retained separately from final passes: the native
text parser dependency was absent, so the regression uses a narrow parser for
its own controlled ASCII metric output without adding a dependency. Stronger
wire-flag assertions exposed the pinned encoder behavior documented above.
Existing HTTP fixture signatures/statuses and bound JSON SQL syntax were corrected
in new test wiring. A pressure-test decoder was corrected for valid spans with no
attributes. The public pre-column revision's scanner annotation was moved onto
its literal after formatting split the original call; the reviewed secret policy
was not broadened. A stale combined run completed migrations but stopped at that
baseline false positive; baseline/image and a standalone migrations gate were
subsequently rerun successfully. Owned resources were cleaned up on each attempt.

Follow-up implementation snapshot (report excluded):
`sha256:41050f644b1574e94f767d03794370e8f79ea4f7e6a1fa3c7be170b3d80f79d6`. <!-- pragma: allowlist secret -->

### Follow-up outcome

F1 is closed in the working implementation and its native regression passes.
The six published criteria are supported by fresh gates and actual telemetry/
process/database checks under the documented configuration. Explicit slot
assignment, possible telemetry loss/reset, stale aggregate collection, the SDK
wire-flag limit and expired Tempo data are documented compatibility/measurement
boundaries. Full M9 acceptance and all ten repository gates are not claimed.
No commit, push, PR, issue-state change or developer application migration occurred.
Final `git diff --check` passed; rehashing the follow-up snapshot found no
implementation changes after the final checks.


## Initial review — historical

The following records the report-only inspection before the authorized correction.
Its findings/statuses and snapshot refer to that earlier working tree.

Date: 2026-11-06 (Asia/Bangkok). Scope: inspection and verification of the current
uncommitted Issue #62 implementation. This report does not change implementation,
GitHub issue state, commits, PRs, deployment or developer application data.
Current M9 is observability; historical M9 deployment is current M15.

Public base Git revision: `fdd4b37ef5807eb396419a365a10612b20176748`. <!-- pragma: allowlist secret -->

Implementation snapshot, excluding this report:
`sha256:10b82fade328943511b8fe4ae546eb4f1ad3309049c8277211d0b343ce8b3bc3`. <!-- pragma: allowlist secret -->

The fingerprint hashes UTF-8 compact, sorted-key JSON mapping each initially
modified/untracked repository path to its SHA-256 content digest, or null for a
deleted file. Pre-existing implementation changes were preserved. Temporary
verification scripts/logs are outside the repository, under
`/tmp/issue62-verification/`; they are local evidence, not a committed evidence
bundle or a durable artifact-retention promise.

Sources: live [Issue #62](https://github.com/ShinningF1eld/RestaurantOS/issues/62),
[observability design](milestone-9-observability-design.md) R4/R5/R12 and applicable
R11 constraints, [task plan T5](milestone-9-observability-task.md#t5-preserve-outbox-trace-context-and-diagnose-worker-attempts),
root engineering instructions, README/current-state, existing #59–#61 verification
reports, current production code, migration harness and tests. No frontend code
was edited; its nested instructions do not govern a backend/report-only change.

### Review result

**Issue #62 is not fully verified for completion. F1 is an independently reproduced
P2 defect in multi-worker process metrics.** The principal trace-context,
transaction, restart, retry/replay and single-worker outage paths are implemented
and have passing evidence. All six required implementation-phase gates passed.
Fresh unit/static and focused integration reruns also pass, but the existing
checks do not detect F1. This qualifies the earlier implementation completion
summary and current-state evidence; it does not invalidate their recorded test
results.

AC numbers below refer to the six acceptance bullets in the live GitHub issue,
in order. Passed means supported within the described local evidence boundary;
it does not mean every expanded failure exercise has been performed.

### Acceptance mapping

| Criterion | Status | Implementation and evidence | Remaining gap |
|---|---|---|---|
| AC1 — optional bounded validated context, atomic append, safe omission, no sensitive metadata or transaction-path export | **Passed** | `core/trace_context.py` accepts exact lowercase W3C version 00, nonzero trace/span IDs and a flags byte. Capture omits absent/nonrecording/error contexts. `events/service.py` stages `traceparent` with the event in the caller transaction, outside v1 payloads. Unit validation/failure tests and real PostgreSQL persistence/rollback tests pass. No exporter call is introduced into append. | The rollback test stages its second event after the originating span has ended, so it directly proves row rollback, not a second non-NULL-context rollback. Same-row transactional behavior is supported by code inspection. |
| AC2 — clean/seeded preservation, NULL historical context, one head, drift check and narrow compatible-code downgrade | **Passed** | Nullable `varchar(55)` migration `d4e9f2a63b85`, matching ORM metadata and covering partial index. Retained clean/seeded migration gate passes, including business snapshots, event/delivery/attempt/receipt/replay preservation across metadata downgrade/re-upgrade, and `alembic check`. Generated SQL was inspected during implementation. Compatibility and index-build locking are documented. | The full migration gate was inspected as retained evidence, not rerun during this report-only inspection. No developer database was selected. |
| AC3 — meaningful publication and actual execution spans, origin links and safe identities, independent asynchronous lifetimes | **Passed** | Publication wraps actual XADD plus fenced observation; outcomes include transport/observation failure and lost claim. Execution opens an independent root span after `_start`, with `Link` from PostgreSQL context and event/correlation/attempt/retry/replay facts. Finalization occurs after effect commit or failure settlement. Actual SDK/OTLP tests inspect independent links, outcomes and canary exclusion. | Contract-rejection records created inside `_start` have existing local diagnostics but no new execution span; a handler is not executed on that path. Fresh exported-span assertions for publication failure/lost-claim branches were not added by this inspection. |
| AC4 — real restart, legacy processing, retry/replay/duplicate distinction and preserved durable effects/totals | **Passed** | Fresh real-process tests kill a worker at an explicit after-claim barrier, then run production `app.worker`; linked spans survive. NULL-context events complete without links. A test-only poison handler produces failed/retried/terminal attempts, trusted operator replay and production repair. Duplicate Redis delivery is ACKed with one diagnostic effect and no additional execution span. Completed-sales processing yields one 12.50 contribution and two receipts during normal/rejecting-Collector runs. | Migrated historical rows and NULL-context worker completion are verified by separate scenarios, not one combined migrate-then-worker rehearsal. See expanded coverage limits below. |
| AC5 — durable backlog/oldest age, per-consumer progress/throughput/retry/terminal metrics and documented state semantics | **Failed** | Feature-owned PostgreSQL aggregates classify queued, active leases, delayed retries, expired processing recovery and terminal work. Recent receipt gauges and process counters/histograms exist; labels are allowlisted. All five backlog states/age and decoded OTLP metric names/labels pass fresh tests. A partial covering index, 15-second cadence, SQL timeout and overall timeout bound collection. | **F1:** independent healthy worker process streams collapse into the same Prometheus series, corrupting operational counter/rate interpretation. Single-worker and durable snapshot behavior do not repair this collision. |
| AC6 — Collector outage independence, bounded lifecycle/export, safe local diagnostics and expired Tempo context limits | **Passed** | Production entrypoint reuses `worker_lifecycle`, bounded SDK queues/export timeouts and bounded retirement wait. Fresh real-process HTTP-503 Collector tests still commit effects/receipts and terminate normally; repair/duplicate tests confirm ACK handling. Existing shared lifecycle/exporter tests pass in the unit suite. Documentation states retained context cannot reconstruct expired Tempo spans. | Fresh worker-specific sustained slow/blackholed-Collector queue-pressure and telemetry recovery/staleness exercises were not performed. The existing #59 shared pipeline and #61 worker-outage evidence are supporting evidence, not new #62 measurements. |

### Findings

#### F1 — P2: independent worker counters overwrite each other in Prometheus

Locations:

- `backend/app/core/telemetry.py:141` supplies only `service.name` in the worker
  resource; every worker uses `restaurantos-worker`.
- `backend/app/modules/events/telemetry.py:73` records process-local cumulative
  operations with bounded operation/consumer/event-type/outcome attributes.
- `monitoring/otel-collector.yaml:258` retains only `service.name` for worker
  metric resources; `:266` retains no producer discriminator in datapoints.
- `monitoring/otel-collector.yaml:282` exposes only `service.name` as the configured
  constant resource label. The native exporter therefore has identical series
  identity for matching observations from distinct worker providers.

**Reproduction:** a temporary, owned Collector used the exact pinned Contrib
**0.164.0** image and the repository's OTLP receiver, worker filter/transform,
batch processor and Prometheus exporter. Only the worker metrics pipeline was
started, with random loopback ingestion/scrape ports and a bounded container.
Two independent real SDK `MeterProvider`s used the same resource and
`WorkerMetrics` construction as current workers. Their start times differed;
no SDK or Collector methods were mocked. The probe represents distinct producer
streams; it did not launch two OS worker processes or change business data.

Each provider recorded the same attributes:
`consumer=analytics`, `event_type=order.completed.v1`, `operation=consumer`,
`outcome=consumer_committed`. Provider A recorded 5 operations and provider B
recorded 9. OTLP/HTTP exports all returned SUCCESS. Native Prometheus scrapes
showed one identical series throughout:

| Observation | Exposed `restaurantos_worker_operations_total` |
|---|---:|
| Export A | 5 |
| Export B, while A remains alive | 9 |
| Quiet cumulative re-export from A | 5 |

The series also carried `job=restaurantos-worker` and
`service_name=restaurantos-worker`; there was no producer label distinguishing
A from B. No process reset, crash, queue loss or export rejection occurred.
Fourteen observed operations are not represented as two independently rateable
streams or an intentional aggregate. Quiet re-export introduces an apparent
counter reset, so service throughput and failure/retry rates can be wrong during
ordinary concurrent-worker operation. Documentation's process-local crash/loss
qualification and warning not to sum duplicate durable gauges do not describe
or solve this healthy-producer overwrite.

The native counter name matches the documented example. The native backlog count
gauge is `restaurantos_worker_deliveries_ratio` because its SDK unit is `1`;
this is a translation observation, not evidence of a separate counter-name bug.

**Required correction:** define intentional multi-producer handling for
process-local instruments. Preserve independently rateable streams using an
explicit controlled-cardinality producer model, or aggregate observations through
a suitable collection design. Do not add business IDs or arbitrary worker UUIDs
as metric labels. Keep durable backlog/progress gauges separately defined so
replicas do not multiply database-derived totals. Add a native Collector regression
that interleaves cumulative exports from two still-live producers and a quiet
re-export; test restart behavior as well. Rerun affected telemetry/gate checks.
No correction was made during this report-only task.

Local probe: `/tmp/issue62-verification/native_metrics.py`.
Output: `/tmp/issue62-verification/native-metrics.log`.
Its owned Collector was removed in `finally`; it did not start or modify the
user's monitoring project, application database or persistent volumes.

### Expanded requirement and definition-of-done coverage

This maps the more detailed implementation request as well as the six published
acceptance bullets. Tests and statements below were inspected in current code;
missing exercises are not treated as implemented defects without reproduction.

| Requirement area | Assessment |
|---|---|
| Capture, bounded representation, valid IDs/flags, NULL on invalid/unavailable/nonrecording context | Implemented; strict parser/link unit tests and recording-span capture test. No baggage/tracestate/vendor data is extracted. Capture exceptions return NULL. |
| Existing correlation independent; context outside payload/schema version | Implemented in append/model; pure envelope contracts unchanged. PostgreSQL test checks v1 and absence of trace metadata from payload. |
| Atomic business/audit/outbox transaction and rollback, no second metadata transaction/export | Existing transaction ownership preserved. Append only flushes. Same-row trace metadata rolls back with its event; narrower direct rollback assertion noted under AC1. |
| One additive revision, single head, metadata agreement, clean/seeded history and safe downgrade | Retained passing migrations gate and final integration drift check. Downgrade drops only the new index/column; compatible code and write-blocking index-build risk documented. |
| Typed relay, stored delivery and attempt context; PostgreSQL authority across restart | `DeliveryClaim`, `StoredDelivery`, `AttemptClaim` carry optional context. `_start` reloads outbox facts, validates Redis references and never accepts trace context from Redis. Restart/fan-out tests pass. |
| Publication outcomes/duration/safe failure category | Actual publication wrapper differentiates publish observation, claim loss, transport failure and observation failure. Monotonic histogram/span timestamps measure operation duration; exporter IO remains SDK-owned. Branch-specific exported telemetry coverage is incomplete. |
| Every actual handler attempt; first/retry/replay/terminal/committed identity | Common execution wrapper includes attempt number, retry cycle and replay ID. Fresh failed/retried/replayed process and direct-service tests inspect distinct attempt IDs. Routing, duplicate and busy returns do not create handler-attempt spans. Contract rejection remains local-only. |
| Claims/fencing, retry policy, receipt/effect atomicity, deduplication and ACK after commit | Existing write paths retained; expanded wrapper delegates unchanged use cases. Real worker tests plus retained full execution/projection suites cover fencing, effect rollback and crash windows. No business contract or event schema change found in inspected diffs. |
| Replay/duplicate cannot inflate analytics/financial totals | New actual-process diagnostic duplicate/replay checks plus 12.50 completed-sales/receipt reconciliation pass. Existing analytics projection/replay tests supply additional retained coverage; new replay telemetry test itself uses a submitted event, not a completed-sales replay. |
| Durable unfinished depth/oldest age and queued/in-flight/retry-delayed/terminal states | PostgreSQL aggregate plus explicit recovery_due state; no Redis-length substitution. Fresh state/age test passes. Succeeded history is excluded via predicate and matching partial covering index. |
| Per-consumer durable progress/throughput, failure/retry/terminal signals | Present for fixed consumers using five-minute receipt gauges, operation/routing counters and duration histograms. **Fails concurrent process-local stream correctness under F1.** Time-window progress and snapshots remain distinct from financial accounting. |
| Metric names/types/units/labels/source/cadence/freshness/reset/loss | Documented in `docs/api/events.md`; actual source OTLP checked. Native probe verifies operation counter and backlog gauge translation. Other native worker metric names/histograms and live Prometheus queries were not comprehensively exercised here. |
| Feature-owned read-only aggregate queries, index/cadence/timeouts | Queries belong to events repository; services own their sessions/transactions. One-second statement timeout, three-second task budget and 15-second cadence are explicit. Large-history query plans, sustained cost and collection timeout/recovery are unmeasured. |
| Optional standalone lifecycle, shared OTLP settings, one provider owner, bounded queue/export/shutdown | Reuses shared lifecycle and resource retirement. Fresh unit/static and actual process termination checks pass. Exporter outages do not enter transaction correctness; shutdown may lose queued observations as documented. |
| Exported secrets/canaries, allowlisted fields, no unbounded business metric labels | Source span attributes and metric labels are allowlisted; links parse fresh context without tracestate. Fresh SDK and actual HTTP protobuf tests reject synthetic canaries. Worker stderr is discarded in several process tests, so those tests do not independently inspect its final JSON privacy. Existing formatter suppresses exception details on inspection. |
| Sampling/retention/expired contexts | Existing ALWAYS_ON provider and independent roots prevent incoming sampling flags from defeating local acceptance. Fixed Tempo retention is unchanged; docs distinguish stored identifiers from expired trace data. No new retention expiry exercise was run. |
| Real-process restart, failure/retry, repair/replay, duplicate, monitoring failure and legacy compatibility | Fresh six-test module passes. Direct assertions validate source trace IDs, distinct attempts, replay visibility, diagnostic deduplication, sales and receipts. Precise combined/harder scenarios below remain untested. |
| Documentation, all required gates and honest completion statement | Contract/testing/current-state docs exist; retained six gate results are real. This report records F1 and untested boundaries, so it does **not** mark all issue criteria complete or accept all M9. |

### Fresh executions for this report

Python **3.12.16**, local macOS/ARM64; installed OpenTelemetry SDK/OTLP HTTP
**1.45.1**, SQLAlchemy **2.0.52**, Alembic **1.19.1**. No dependency installation,
resolution or lock change occurred. Commands are from the repository root unless
noted. Fresh Docker checks used only named disposable test resources.

| Command / procedure | Result and evidence |
|---|---|
| `backend/.venv/bin/python scripts/validate.py --gate backend-unit --gate backend-static --no-install` | **518 passed** in 5.82s; Ruff lint/format, mypy **171 app sources** and harness static checks passed. `/tmp/issue62-verification/unit-static.log`. |
| `backend/.venv/bin/python /tmp/issue62-verification/focused.py` | **6 passed** in 8.39s, 27 existing deprecation warnings; real migrated disposable PostgreSQL/Redis, decoded OTLP, production worker restart/outage and repair/duplicate scenarios. `/tmp/issue62-verification/focused.log`. |
| `backend/.venv/bin/python -u /tmp/issue62-verification/native_metrics.py` | Probe completed with successful real HTTP exports and owned cleanup. **F1 reproduced**, 5 -> 9 -> 5 in one counter series. `/tmp/issue62-verification/native-metrics.log`. This is a failing correctness observation even though the diagnostic script exits normally. |
| `git diff --check` | Checked before report creation; no whitespace errors. Final report/diff verification is recorded below. |

The focused runner imports the repository's `validate.services(False)` and
`test_support.disposable_postgres.disposable_database`, passes the owned test URL,
uses `database.environment`, upgrades only that new database with
`python -m alembic upgrade head` from `backend/`, then executes
`python -m pytest tests/integration/test_event_telemetry.py -xq --tb=short`.
Both resource owners unwind on failure. The temporary runner is not required to
reproduce the tracked tests: the normal `backend-integration` gate selects them.

### Retained implementation-phase shared checks

These logs were inspected, not rerun as complete gates during this report.
They belong to the preceding implementation work in this chat, not remote CI.

| Exact command | Retained result |
|---|---|
| `backend/.venv/bin/python scripts/validate.py --gate backend-unit --no-install` | **518 passed**, one existing warning; `/tmp/issue62-unit.log`. Fresh full unit rerun above confirms current behavior. |
| `backend/.venv/bin/python scripts/validate.py --gate backend-static --no-install` | Ruff/format/mypy and harness checks passed; `/tmp/issue62-static.log`. Fresh rerun above also passed. |
| `backend/.venv/bin/python scripts/validate.py --gate backend-integration --no-install` | Final run **363 passed, 1 skipped** in 364.94s, 1,030 existing warnings; `alembic check` found no new operations; disposable cleanup passed. `/tmp/issue62-integration-final.log`. The skip is the existing opt-in stored-API monitoring test requiring `TEST_MONITORING_ENDPOINT`. |
| `backend/.venv/bin/python scripts/validate.py --gate migrations --no-install` | Clean unique-head upgrade/drift check, seeded business preservation, metadata/index downgrade/re-upgrade, history guards and backup/restore rehearsal passed; `/tmp/issue62-migrations.log`. |
| `backend/.venv/bin/python scripts/validate.py --gate baseline --no-install` | Compose models, installed dependency consistency and reviewed-baseline secret scan passed; `/tmp/issue62-baseline.log`. |
| `backend/.venv/bin/python scripts/validate.py --gate image --no-install` | Locked nonroot API/worker and standalone frontend build/runtime checks passed; startup did not migrate the disposable DB; `/tmp/issue62-image.log`. |
| `backend/.venv/bin/python scripts/check-monitoring-config.py` | Collector, Prometheus, Loki and Tempo pinned native parsers passed; `/tmp/issue62-parser.log`. Parser checks alone do not establish runtime signal correctness. |

Retained failures are not substituted for these final results. Initial unit runs
failed old exact pipeline-set assertions; those were extended for the additive
worker pipelines. Initial test assumptions about SDK flags and process cleanup
were corrected; leaked test workers were identified by their pytest parent and
stopped. A migration test's physical schema-column-order comparison was reset
after its deliberate drop/re-add cycle. Public migration revision IDs received
the existing inline scanner annotation. One intermediate integration run passed
362 tests but failed drift checking because its database predated the newly added
index; the final run above used the final migration and passed drift checking.

For this report, two initial native-probe readiness attempts incorrectly required
a nonempty scrape before any metric was sent. A successful empty HTTP response is
now accepted; both initial probe containers were removed. That harness error is
separate from F1, which was reproduced only after successful exports and scrapes.

### Compatibility, coverage limits and next actions

No event version, public route/operator interface, dependency, financial behavior,
transaction ownership, claim fencing or Redis ACK ordering was changed by this
verification task. All pre-existing implementation files remain unchanged.

The six fresh tests do not constitute every detailed acceptance exercise:

- They create origins with a real SDK test tracer. Actual FastAPI HTTP observation
  and transactional append were inspected, but a single fresh authenticated
  FastAPI business-command -> restarted worker -> stored Tempo investigation was
  not performed.
- Legacy migration preservation and NULL-context worker processing are separate
  checks. A worker processing the exact seeded pre-column rows after upgrade in
  one rehearsal is not demonstrated. Likewise, the traced rollback test's
  rolled-back event has no active origin at append, as noted under AC1.
- Source OTLP link assertions chiefly compare originating **trace IDs**. They do
  not comprehensively assert originating **span IDs and flags** across actual
  process restart, all three consumer types, each publication failure branch or
  hostile Redis metadata. Parser/unit construction and code inspection support
  these paths but do not replace those missing runtime assertions.
- The outage process test uses an HTTP receiver that decodes and rejects telemetry
  with 503. A worker-specific sustained slow/blackholed Collector pressure test,
  bound on observed worker queue/memory under that workload, restart after telemetry
  recovery, and automatic metric collection stale/recovery assertions are not
  demonstrated by this new test module. Shared API lifecycle tests and historical
  #61 worker absence tests provide narrower supporting evidence.
- The native probe exercises the actual worker metrics Collector path, not all
  five monitoring stores or Tempo retention. No new dashboards, alerts, long-term
  cost/capacity objective, remote CI, hosted environment, AMD64 runtime or full
  ten-gate M9 acceptance is claimed.

Resolve F1 and add the interleaved native-export regression before marking AC5
complete. Strengthen the missing exact link and failure/recovery assertions where
needed to satisfy the expanded execution request, then rerun the affected gates
and preserve the distinction between fresh, retained and untested evidence.
Passing gates alone do not close the newly reproduced defect. No implementation
fix, commit, push, PR, issue checkbox/status change or application migration was
performed as part of this report.

Final report verification: `git diff --check` passed. Rehashing every path in the
initial implementation snapshot found **zero pre-existing file changes**. The
only repository file added by this report task is this verification document.
