# Milestone 9 observability task plan

Status: Published — all ten issues and milestone assignments verified
Task-plan revision: 1
Updated: 2026-10-31 (Asia/Bangkok)
Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1; referenced planning baseline accepted with publication approval on 2026-10-31 (source snapshot retains its original Draft header)
Source SHA-256: `C34C0071E265487168EF8C313CF222E227E206F664B9EAA050834EF913AC4A8B`
Inspected repository HEAD: `bda038a7ad3fc88cc84cbc7a4c324c895363f8c0`
Local state before planning: the observability design directory was untracked; no implementation changes
Target repository: `ShinningF1eld/RestaurantOS`, confirmed from origin
Publication approval: user approved revision 1 on 2026-10-31: "Yes publish it to github issues. Also assign milestone 9 to those issue". The reviewed issue scope and referenced design baseline are accepted for planning; implementation acceptance remains unverified.
GitHub milestone: [Milestone 9 Observability and operational readiness](https://github.com/ShinningF1eld/RestaurantOS/milestone/4) (GitHub number 4, product M9), created on 2026-10-31 for this authorized assignment.

The user approved this exact ten-issue set for GitHub publication and requested
M9 milestone assignment on 2026-10-31. Issues #58–#67 were created and fetched back
to verify titles, full bodies, dependency links and milestone assignment. The
source snapshot and issue acceptance criteria are unchanged. No implementation,
commit, push or PR was performed. Numerical objectives still require T8 evidence
and acceptance; publishing tasks does not mark their criteria complete.

Current M9 is observability. Historical `docs/milestone9/` refers to deployment,
now M15. Preserve those historical artifacts and publish titles with the explicit
`[M9 Observability]` prefix. The authorized M9 milestone was created and assigned;
assignees and labels remain unset.

## Ordered tasks

| ID | Outcome | Requirements | Depends on | Publication |
|---|---|---|---|---|
| T1 | Prove and package the bounded local monitoring stack | R1, R2, R6, R9 | None | [#58](https://github.com/ShinningF1eld/RestaurantOS/issues/58) |
| T2 | Instrument FastAPI requests with safe logs, metrics and traces | R3, R5, R12 | T1 | [#59](https://github.com/ShinningF1eld/RestaurantOS/issues/59) |
| T3 | Trace Next.js server requests through the existing API client | R3, R5, R9 | T2 | [#60](https://github.com/ShinningF1eld/RestaurantOS/issues/60) |
| T4 | Expose PostgreSQL and Redis diagnostics with restricted collection | R2, R5, R12 | T2 | [#61](https://github.com/ShinningF1eld/RestaurantOS/issues/61) |
| T5 | Preserve outbox trace context and diagnose worker attempts | R4, R5, R12 | T2 | [#62](https://github.com/ShinningF1eld/RestaurantOS/issues/62) |
| T6 | Expose honest business activity and projection freshness metrics | R5, R11, R12 | T2, T5 | [#63](https://github.com/ShinningF1eld/RestaurantOS/issues/63) |
| T7 | Provision four linked Grafana operator dashboards | R5, R7, R11, R12 | T3, T4, T5, T6 | [#64](https://github.com/ShinningF1eld/RestaurantOS/issues/64) |
| T8 | Measure a local baseline and agree objectives and alert thresholds | R2, R8, R10 | T7 | [#65](https://github.com/ShinningF1eld/RestaurantOS/issues/65) |
| T9 | Validate local alerts and six incident response exercises | R5, R8, R9, R10 | T8 | [#66](https://github.com/ShinningF1eld/RestaurantOS/issues/66) |
| T10 | Enforce observability regressions and record M9 acceptance | R1–R12; both roadmap exit criteria | T9 | [#67](https://github.com/ShinningF1eld/RestaurantOS/issues/67) |

## Coverage and sequencing

T1 combines the bounded feasibility check with a reusable local stack. T2 establishes
shared API signal/privacy conventions. After T2, T3 (SSR), T4 (infrastructure) and
T5 (events) are dependency-independent, though shared files/dependency locks require
coordination. T6 follows T5 for projection freshness. T7 integrates those signals;
T8 measures them and obtains numeric target acceptance; T9 implements final alerts
and incident exercises; T10 enforces regressions and records milestone acceptance.
These are dependency notes, not instructions to spawn agents.

Each implementation issue owns its focused regressions. T10 does not postpone
privacy, migration or business-correctness testing until the end. Baseline
measurement deliberately precedes final alert thresholds to avoid a dependency
cycle or inventing values the design left open.

| Requirement | Primary tasks | Final proof |
|---|---|---|
| R1 Five-service stack | T1 | T10 |
| R2 Resource limits | T1, T4, T8 | T9, T10 |
| R3 Server request tracing | T2, T3 | T7, T10 |
| R4 Durable correlation | T5 | T9, T10 |
| R5 Safe best-effort diagnostics | T2–T7 | T9, T10 |
| R6 Access and retention | T1 | T10 |
| R7 Four dashboards | T7 | T10 |
| R8 Local actionable alerts | T8, T9 | T10 |
| R9 Two workflows and isolation | T1, T3, T9 | T10 |
| R10 Measured operational proof | T8, T9 | T10 |
| R11 Honest business signals | T6, T7 | T10 |
| R12 Limited infrastructure collection | T4, T5, T6 | T10 |

The source's S1 maps to T1; S2 to T2–T4; S3 to T5; S4 to T6/T7/T9;
S5 to T8–T10. This is finer task decomposition, not a change in milestone scope.
All R IDs refer to this observability design, not historical deployment R IDs.

## Inspection and boundaries

Inspected the design, roadmap mapping, existing M8 task format, shared gate runner,
CI workflow, SSR API transport, catalog cache and event operator status interface.
Existing telemetry is JSON/request/event diagnostics, not the proposed monitoring
stack. Existing event status queries and analytics projection can inform bounded
feature-owned collection; their existence does not prove cheap scrape behavior.

There is no repository issue template under `.github/`; bodies follow the
invoked skill template and existing task-plan convention. Available GitHub issue
search found no `observability` matches in either open or closed states on
2026-10-31. A broader repository issue search returned prior M6–M8 tasks, not a
matching current-M9 set. Search results are not a permanent absence guarantee;
repeat identity/title searches immediately before publication and inspect any
plausible matches. GitHub CLI is not installed; the connected GitHub search tool
is usable. Publication later used the connected issue tools; the missing milestone
was created through GitHub's UI because the connector does not expose milestone
creation/listing. Pre-publication search again returned no observability matches.

Schema risk is owned by T5: additive nullable trace metadata, legacy preservation,
one Alembic head, downgrade compatibility and disposable migration verification.
No validation or task preparation migrates the application database. No change to
business transactions, audit atomicity, auth/tenant policies, stock consumption,
cache freshness, event receipts or replay guarantees is authorized incidentally.

Keep supported Python 3.12/Node 24 and committed dependency locks. New telemetry
packages require source/lock updates under docs/testing/dependencies.md; no unrelated
upgrades. Preserve frontend/AGENTS.md and consult installed Next.js documentation.
Numeric SLOs, alert windows, exact images/SDKs and collector permission details are
explicit implementation/measurement outputs, not preapproved fabricated values.

Verification commands below use gate names as shorthand for
`./scripts/validate.ps1 -Gate <name> -NoInstall` after a locked dependency install.
Run gates individually when selecting multiple; final validation is
`./scripts/validate.ps1` without skips. The Linux/macOS equivalent is
`backend/.venv/bin/python scripts/validate.py` with `--gate <name> --no-install`
for a partial check. New scenario commands must be documented by their owning
issue; this plan does not pretend those scripts already exist.

## Published issue bodies

Each body below matches its verified published issue. Dependencies use confirmed
issue links; local task IDs and identity markers remain stable. The source design
is still local/untracked, so its path/version is identified as text rather than an
unverified GitHub blob URL.

### T1: Prove and package the bounded local monitoring stack

Published GitHub title: **[M9 Observability] Prove and package the bounded local monitoring stack**

#### Purpose and references

Resolve the unproven five-service resource and interoperability assumptions before broad application instrumentation.

Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1, 2026-10-31;
requirements R1, R2, R6, R9. This source belongs to current M9 observability, not M15
deployment. Task-plan revision 1; acceptance remains unverified.

#### Scope

New monitoring Compose/configuration assets, isolated synthetic telemetry generator, setup documentation and lifecycle helpers. Keep the five agreed services; no cloud resources or application database migration.

#### Dependencies

None.

#### Acceptance criteria

- [ ] Pin Prometheus, Grafana, Tempo, Loki and upstream Collector Contrib versions/digests; demonstrate synthetic metrics, logs and traces arriving through the intended collector pipelines and visible through provisioned Grafana data sources.
- [ ] Record a bounded prototype workload, duration, versions, per-service/aggregate memory and CPU, disk growth and telemetry counts. Configure an initial combined 2 GB monitoring memory budget and report OOM/restarts/drops. If infeasible, preserve the result and propose an adjustment rather than silently raising the budget.
- [ ] Provide documented startup/shutdown for host-development connectivity and an isolated container acceptance network. Bind Grafana and necessary host OTLP ingress to loopback; keep storage endpoints internal, avoid frontend port 3000, and configure Grafana authentication without tracked secrets.
- [ ] Configure seven-day metrics and three-day log/trace retention, persistent restart storage and actual cleanup mechanisms. Verify retention with accelerated isolated fixtures and distinguish retention duration from byte limits; record an initial disk budget based on the prototype.
- [ ] Bound collector queues/retries/timeouts and expose self-health/export failures. A stopped destination must not produce unbounded collector memory. Preserve the distinction between stale/missing telemetry and zero activity.
- [ ] Lifecycle and failure cleanup own only test resources. Normal development shutdown retains monitoring data; synthetic acceptance cleanup cannot delete developer volumes. Record per-service limits, normal sampling proposal and receiver compatibility as implementation evidence.

#### Verification

Run Compose/config validation and the isolated three-signal smoke in both connection modes; test normal restart persistence, destination outage, accelerated retention and intentional harness failure cleanup. Run baseline and image gates where affected. No application instrumentation or final M9 capacity claim is required here.

<!-- github-plan: docs/milestone9-observability/milestone-9-observability-design.md | T1 -->

### T2: Instrument FastAPI requests with safe logs, metrics and traces

Published GitHub title: **[M9 Observability] Instrument FastAPI requests with safe logs, metrics and traces**

#### Purpose and references

Give API operations usable latency/error diagnostics without leaking data or coupling telemetry to business availability.

Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1, 2026-10-31;
requirements R3, R5, R12. This source belongs to current M9 observability, not M15
deployment. Task-plan revision 1; acceptance remains unverified.

#### Scope

backend/app/core/, app/http/, API startup/settings, dependency source/locks and focused backend tests. Reuse request IDs; infrastructure and worker detail are owned by T4/T5.

#### Dependencies

[T1 (#58)](https://github.com/ShinningF1eld/RestaurantOS/issues/58).

#### Acceptance criteria

- [ ] Initialize one bounded, configurable telemetry pipeline per API process; disabled monitoring starts normally, and collector absence does not prevent startup, request completion or bounded shutdown.
- [ ] Export request rate, status/error classification, latency histograms supporting P50/P95/P99 and in-flight requests by bounded normalized route/method dimensions. Unknown paths do not create unlimited label values; cancellation and exceptions release in-flight accounting.
- [ ] Correlate API spans and structured logs with existing request IDs and trace/span IDs. Validated trace context can continue trusted upstream calls; malformed context does not reject a valid business request and is never authorization evidence.
- [ ] Filter at source and collector: exclude credentials, cookies, request/response bodies, query values and sensitive exception details. Test framework, validation and unhandled-exception paths with synthetic canaries and inspect actual exported signals, not only formatter output.
- [ ] Keep structured local diagnostics available without duplicate log ingestion. Export queues, retry time and shutdown flushing are bounded; stopped/slow collection does not change committed order/audit behavior.
- [ ] Preserve public route/error/session/CSRF and health/readiness contracts. Add only bounded observability configuration, update Python .in files and hashed locks together, and document metric units, types and error categories.

#### Verification

Run backend-unit, backend-integration, backend-static and baseline; exercise actual API exports against T1, including malformed headers, cancellations, a synthetic server error and collector outage. Use real PostgreSQL for business invariants. Run image if runtime packaging changes.

<!-- github-plan: docs/milestone9-observability/milestone-9-observability-design.md | T2 -->

### T3: Trace Next.js server requests through the existing API client

Published GitHub title: **[M9 Observability] Trace Next.js server requests through the existing API client**

#### Purpose and references

Connect SSR activity to API diagnostics while preserving cookie security and the existing renewal flow.

Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1, 2026-10-31;
requirements R3, R5, R9. This source belongs to current M9 observability, not M15
deployment. Task-plan revision 1; acceptance remains unverified.

#### Scope

frontend server instrumentation, lib/api/server.ts, runtime configuration, package locks and focused server/browser tests. No browser SDK, client interaction capture or new product UI.

#### Dependencies

[T2 (#59)](https://github.com/ShinningF1eld/RestaurantOS/issues/59).

#### Acceptance criteria

- [ ] Consult installed Next.js documentation and frontend/AGENTS.md before code. Register instrumentation in the supported server entry point with runtime guards and no browser bundle inclusion.
- [ ] An authenticated SSR request produces a Next.js server span and an associated API trace through the configured trusted API destination in both host and container modes.
- [ ] Continue forwarding only the existing access cookie for authentication, with no-store and redirect protections preserved. SSR 401s still use browser renewal; server instrumentation neither rotates cookies nor replays authentication requests.
- [ ] Propagate only validated trace headers to the intended API destination; never forward arbitrary inbound baggage, headers or trace metadata to unrelated destinations.
- [ ] Exported frontend server logs/spans omit cookies, credentials, private HTML, request bodies and sensitive URL values. Test synthetic canaries and collector outage without changing rendered authorization behavior.
- [ ] Document that direct browser API calls start at the API and client/navigation timing is deferred. Update committed npm lock and prove the standalone production image supports the chosen server instrumentation.

#### Verification

Run frontend-tests, frontend-static, frontend-build, browser and image for changed packaging. Use real SSR/API/collector tests for correlation, expired-session renewal and tenant isolation; keep auth browser traces disabled.

<!-- github-plan: docs/milestone9-observability/milestone-9-observability-design.md | T3 -->

### T4: Expose PostgreSQL and Redis diagnostics with restricted collection

Published GitHub title: **[M9 Observability] Expose PostgreSQL and Redis diagnostics with restricted collection**

#### Purpose and references

Distinguish application latency from pool, database, cache and Redis pressure using low-cost read-only signals.

Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1, 2026-10-31;
requirements R2, R5, R12. This source belongs to current M9 observability, not M15
deployment. Task-plan revision 1; acceptance remains unverified.

#### Scope

API/worker engine hooks, shared Redis adapter and feature cache observations, collector PostgreSQL/Redis receiver configuration and monitoring identity setup. No business schema redesign or auth/cache policy changes.

#### Dependencies

[T2 (#59)](https://github.com/ShinningF1eld/RestaurantOS/issues/59).

#### Acceptance criteria

- [ ] Instrument SQL duration, slow-operation counts, transaction failures and configured/used/waiting pool capacity where supported; distinguish API and worker pools. Do not count normal read teardown rollback as a failed business transaction.
- [ ] Prove pool measurements on real pooled processes rather than the HTTP test adapter's NullPool. Slow query diagnostics expose safe operation categories and timings without SQL text, bound values or connection credentials.
- [ ] Collect read-only PostgreSQL connection, transaction and lock statistics using a dedicated account with the required minimum grants; test required reads succeed and unauthorized business writes fail.
- [ ] Collect Redis latency/errors and server memory/evictions, and application cache hit/miss/bypass outcomes. Distinguish cache effectiveness from Redis server-wide keyspace statistics and auth limiter behavior.
- [ ] Record exact receiver metric mappings, units, versions, grants, collection cadence/timeouts and resource cost. Do not grant Grafana direct SQL access or collect Redis keys/command arguments; missing data is not exported as healthy zero.
- [ ] Stopped DB/Redis/collector collection produces visible failure/staleness without expanding pool limits or changing cache age, auth fallback, transaction or worker durability contracts.

#### Verification

Run backend-unit/backend-integration/backend-static and baseline; test real restricted-role permissions, overlapping pool exhaustion, bounded query collection and Redis outage/recovery in isolation. Use T1 stack to inspect actual metrics and canary exclusion. Run image for configuration/runtime packaging changes.

<!-- github-plan: docs/milestone9-observability/milestone-9-observability-design.md | T4 -->

### T5: Preserve outbox trace context and diagnose worker attempts

Published GitHub title: **[M9 Observability] Preserve outbox trace context and diagnose worker attempts**

#### Purpose and references

Keep API-to-worker investigation useful across delayed delivery, restarts and retry cycles without changing event correctness.

Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1, 2026-10-31;
requirements R4, R5, R12. This source belongs to current M9 observability, not M15
deployment. Task-plan revision 1; acceptance remains unverified.

#### Scope

events service/contracts/repository/claims, relay and consumer execution, worker telemetry lifecycle, one additive Alembic revision and migration tests. Preserve event payload versions and existing public operator interfaces.

#### Dependencies

[T2 (#59)](https://github.com/ShinningF1eld/RestaurantOS/issues/59).

#### Acceptance criteria

- [ ] Add optional bounded validated trace context to outbox storage in the caller's existing transaction; missing or invalid context is omitted safely. Store no baggage or sensitive data, and perform no network export inside business transactions.
- [ ] Clean and seeded legacy upgrades retain all events, delivery/receipt/replay history, order snapshots and stock data; legacy rows have no fabricated context. Maintain one migration head and pass alembic check; review downgrade SQL and compatible-code requirements.
- [ ] Publication and each actual consumer attempt create meaningful spans linked to the originating context, with existing event/correlation/attempt identities in safe metadata. Do not hold HTTP spans open while waiting for asynchronous work.
- [ ] Real process restart preserves links for new events; legacy events still complete. Retry/replay/duplicate delivery remain distinguishable, and successful replay does not duplicate durable effects or business totals.
- [ ] Export durable backlog depth/oldest age, per-consumer progress/throughput, retry and terminal-failure signals with documented definitions. Distinguish queued, in-flight, retry-delayed and terminal work; Redis stream length alone is not the durable backlog.
- [ ] Worker collector outage does not block claims, effects or commit/ACK handling; bounded flush/shutdown and local safe diagnostics remain. Document that expired Tempo data cannot be reconstructed from retained trace context.

#### Verification

Run backend-unit, backend-integration, backend-static, migrations, baseline and image for worker changes. Exercise real relay/consumer processes, restart, failed attempt, duplicate delivery, repair/replay, collector outage and legacy events; reconcile database effects and inspect exported trace links.

<!-- github-plan: docs/milestone9-observability/milestone-9-observability-design.md | T5 -->

### T6: Expose honest business activity and projection freshness metrics

Published GitHub title: **[M9 Observability] Expose honest business activity and projection freshness metrics**

#### Purpose and references

Provide useful business signals without turning best-effort monitoring into an accounting system or inflating totals through replay.

Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1, 2026-10-31;
requirements R5, R11, R12. This source belongs to current M9 observability, not M15
deployment. Task-plan revision 1; acceptance remains unverified.

#### Scope

Feature-owned orders/inventory/alerts/analytics aggregate interfaces and bounded telemetry collection. Reuse current projections and authorization/trusted-operator boundaries; no new tenant screens or M10 reporting definitions.

#### Dependencies

[T2 (#59)](https://github.com/ShinningF1eld/RestaurantOS/issues/59), [T5 (#62)](https://github.com/ShinningF1eld/RestaurantOS/issues/62).

#### Acceptance criteria

- [ ] Observe submissions, completions and cancellations only after a successful commit; rollback, no-op and idempotent replay do not increment the corresponding successful transition observation. Document loss/reset limitations of process-local counters.
- [ ] Expose stock-related rejected command attempts separately from active low-stock state and episode activity. Clearly distinguish repeated rejected attempts from unique business incidents.
- [ ] Read durable completed-sales totals from existing projection semantics, explicitly grouped by creation date in UTC with a defined displayed period. Values may decrease after permitted deletion and must not be represented as a monotonic counter.
- [ ] Keep fixed-precision PostgreSQL values authoritative. Document visualization conversion/units and currency assumptions; do not silently aggregate incompatible currencies or claim financial-reporting guarantees.
- [ ] Show collection freshness separately from projection lag, using relevant pending delivery counts/age. An empty/stopped collector or queued completion cannot appear as a fresh zero or complete projection merely because a scrape succeeded.
- [ ] Use bounded feature-owned read queries and timeouts, with no tenant/user/order/event IDs as metric labels and no sensitive payloads. Compare query cost against seeded data; preserve scoped API access and restrict aggregate visibility to the local operator boundary.

#### Verification

Run backend-unit/backend-integration/backend-static and baseline. Use real transactions, rollback, idempotent retry, receipt replay, out-of-order completion/deletion and stale/failed collection; reconcile exported durable aggregates to PostgreSQL and verify safe bounded label sets.

<!-- github-plan: docs/milestone9-observability/milestone-9-observability-design.md | T6 -->

### T7: Provision four linked Grafana operator dashboards

Published GitHub title: **[M9 Observability] Provision four linked Grafana operator dashboards**

#### Purpose and references

Turn collected signals into repeatable investigations, with accurate units, states and cross-signal links.

Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1, 2026-10-31;
requirements R5, R7, R11, R12. This source belongs to current M9 observability, not M15
deployment. Task-plan revision 1; acceptance remains unverified.

#### Scope

Version-controlled Grafana dashboard/data-source provisioning and dashboard verification fixtures. Reuse T1 access controls; no RestaurantOS UI changes and no alert threshold selection here.

#### Dependencies

[T3 (#60)](https://github.com/ShinningF1eld/RestaurantOS/issues/60), [T4 (#61)](https://github.com/ShinningF1eld/RestaurantOS/issues/61), [T5 (#62)](https://github.com/ShinningF1eld/RestaurantOS/issues/62), [T6 (#63)](https://github.com/ShinningF1eld/RestaurantOS/issues/63).

#### Acceptance criteria

- [ ] Provision service overview, database/Redis, background processing and business activity dashboards from a clean stack with stable identifiers and working data-source references; no required manual UI edits.
- [ ] Overview shows API rate/errors/P50/P95/P99/in-flight requests plus collector health/loss; infrastructure shows defined pool/query/lock/cache/Redis signals; background shows durable backlog, age, retries and terminal failures.
- [ ] Relevant panels link to correctly filtered Loki logs and Tempo traces. Demonstrate an SSR/API operation and linked worker attempt; document behavior when the original trace has expired.
- [ ] Business panels label creation-date UTC sales, period, units, operational-counter resets and projection freshness correctly. Replayed effects do not create misleading growth.
- [ ] Empty activity, unavailable sources and stale data are distinguishable. Expected conflicts/authorization failures/rate limits are not silently mixed into unexpected-server-error panels.
- [ ] Sanitized screenshots or API-verified query outputs from synthetic fixtures prove each panel's query, unit and filters; dashboards expose no customer/order/tenant identifiers or secrets.

#### Verification

Validate provisioning and dashboard queries against T1 and real seeded API/worker data. Inspect rendered Grafana views and cross-links, including no-data/outage states; retain sanitized evidence. Run baseline and affected configuration/static checks.

<!-- github-plan: docs/milestone9-observability/milestone-9-observability-design.md | T7 -->

### T8: Measure a local baseline and agree objectives and alert thresholds

Published GitHub title: **[M9 Observability] Measure a local baseline and agree objectives and alert thresholds**

#### Purpose and references

Choose realistic service objectives and sustained-alert settings from measured behavior before treating them as acceptance criteria.

Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1, 2026-10-31;
requirements R2, R8, R10. This source belongs to current M9 observability, not M15
deployment. Task-plan revision 1; acceptance remains unverified.

#### Scope

Reproducible isolated workload, measurement report and documented proposed/accepted thresholds. No invented latency promise, production capacity claim or cloud load test.

#### Dependencies

[T7 (#64)](https://github.com/ShinningF1eld/RestaurantOS/issues/64).

#### Acceptance criteria

- [ ] Declare dataset, read/write mix, concurrency/rate, warmup, measurement duration, repetitions and reset method before running; record exact source, images, settings and host/Docker capacity. Use synthetic data and an off-by-default acceptance environment.
- [ ] Measure per-route reads/commands/SSR timing, unexpected errors, event commit-to-effect freshness, pool/queue behavior and telemetry volume. Report expected business conflicts separately and retain failed repetitions rather than averaging them away.
- [ ] Compare instrumentation enabled and disabled under equivalent declared workloads to characterize overhead. Record memory/CPU/disk and available drop/export evidence; 100% acceptance tracing must not be silently sampled away.
- [ ] Evaluate the combined five-service 2 GB budget and overall 7.49 GB Docker constraint with application/test overhead included; propose adjustments explicitly if the target is infeasible.
- [ ] Produce specific proposed local latency/error/freshness objectives and alert evaluation/sustained/recovery windows, minimum traffic and no-data behavior with reasons tied to the measurements.
- [ ] Record explicit acceptance of numeric objectives before T9 finalizes rules and before milestone acceptance. Until then mark this task pending decision; baseline results alone do not approve thresholds or establish hosted guarantees.

#### Verification

Run the documented workload with complete raw sanitized results, repeatability details and healthy data reconciliation. Review metric denominators and latency units; distinguish observation from approved targets. This measurement task does not substitute for full gates.

<!-- github-plan: docs/milestone9-observability/milestone-9-observability-design.md | T8 -->

### T9: Validate local alerts and six incident response exercises

Published GitHub title: **[M9 Observability] Validate local alerts and six incident response exercises**

#### Purpose and references

Demonstrate that operational signals produce actionable local alerts and documented recovery without endangering developer data.

Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1, 2026-10-31;
requirements R5, R8, R9, R10. This source belongs to current M9 observability, not M15
deployment. Task-plan revision 1; acceptance remains unverified.

#### Scope

Provisioned Grafana rules, isolated local notification receiver, fault harness, incident runbooks and dated evidence. External delivery and hosted guarantees stay deferred.

#### Dependencies

[T8 (#65)](https://github.com/ShinningF1eld/RestaurantOS/issues/65).

#### Acceptance criteria

- [ ] Implement the accepted sustained API-error, DB-saturation, old-work and repeated-job-failure rules using T8 definitions. Record firing/resolution/no-data states and locally captured notifications, including configured grouping/deduplication and recovery behavior.
- [ ] Exercise an API failure and real DB pool exhaustion: sanitized correlated evidence appears, failures remain bounded, alert transitions are correct, and recovery leaves business state/sessions consistent.
- [ ] Exercise Redis outage and worker stop/restart: existing fallback/durability behavior holds, backlog/age is visible, alerts recover and all eligible durable effects reconcile after recovery.
- [ ] Exercise repeated consumer failure followed by documented inspection/repair/replay. Retain original/replay identities, retries and terminal state; no duplicate business effect is introduced.
- [ ] Exercise collector and telemetry destination outages: orders/worker effects remain correct, queues/memory/shutdown remain bounded, and stale intervals plus available drop evidence are visible after recovery. Explicitly document limits when Grafana itself is unavailable.
- [ ] Provide response instructions for DB exhaustion, Redis outage, backlog, repeated failure, failed migration and compatible rollback. Reuse existing backup/maintenance rules; perform only disposable exercises and claim no hosted rollback proof.
- [ ] Fault setup uses isolated names/ports/_test databases, no production fault endpoints and no sleeps as proof of lock overlap. Intentional test failure cleans up only owned resources and retains sanitized evidence; authentication traces remain disabled.

#### Verification

Run all six scenarios through real API/PostgreSQL/Redis/worker/monitoring, capture firing and resolved notification payloads locally, assert business reconciliation and cleanup on success/failure. Run affected backend/browser/image gates. No external messages are sent.

<!-- github-plan: docs/milestone9-observability/milestone-9-observability-design.md | T9 -->

### T10: Enforce observability regressions and record M9 acceptance

Published GitHub title: **[M9 Observability] Enforce observability regressions and record M9 acceptance**

#### Purpose and references

Make critical observability guarantees repeatable and assemble exact-source evidence without confusing local M9 with deferred M15 deployment.

Source: `docs/milestone9-observability/milestone-9-observability-design.md`, revision 1, 2026-10-31;
requirements R1–R12; both roadmap exit criteria. This source belongs to current M9 observability, not M15
deployment. Task-plan revision 1; acceptance remains unverified.

#### Scope

Shared validation integration, missing cross-slice regressions, documentation/evidence, requirement mapping and final local/CI checks. Reuse slice tests instead of duplicating them.

#### Dependencies

[T9 (#66)](https://github.com/ShinningF1eld/RestaurantOS/issues/66).

#### Acceptance criteria

- [ ] Map every R1–R12 acceptance criterion and both roadmap exits to executable checks and dated results. Include one full request-to-database/outbox/worker investigation and a deliberately injected failure with documented response.
- [ ] Integrate bounded deterministic smoke/privacy/correlation/outage regressions into appropriate existing required gates; document heavier baseline/incident acceptance commands separately and execute them for final acceptance. Critical checks cannot exist only as optional unrun scripts.
- [ ] Keep all ten shared gates and the exact Milestone 6 acceptance aggregate enforced; if workflow/enforcement policy changes, reproduce required-check failure/pending/success behavior per docs/testing/enforcement.md.
- [ ] Full locked-install validation on supported Python 3.12/Node 24 passes all ten gates, including clean/seeded migrations and production images; final complete PR CI passes for the candidate revision when authorized. Record exact commands, revisions, outcomes and omissions.
- [ ] Prove both supported development modes, resource limits, retention cleanup, local alert delivery, sensitive-data exclusion and monitoring-loss behavior using final configuration. Confirm acceptance failures remain failures and test resources are cleaned.
- [ ] Update README, current-state, API/architecture/runbook/testing references and roadmap evidence only within M9 scope, preserving historical M15 identifiers. Record migration needs separately from actual application revision; do not claim application migration or hosted readiness.
- [ ] Keep unsatisfied numerical targets, missing CI, resource failures or unresolved requirements open. Document browser tracing, external notifications, dedicated error lifecycle, M10 analytics and hosted guarantees as deferred.

#### Verification

Run ./scripts/validate.ps1 with committed locks, all six final incident exercises and the approved baseline/objective checks; review final PR CI only when publication/PR operations are separately authorized. Audit requirement coverage and sanitized retained artifacts. No historical green run establishes this revision's acceptance.

<!-- github-plan: docs/milestone9-observability/milestone-9-observability-design.md | T10 -->

## Publication record

| Task | Attempt/result | Issue number and URL | Remaining action |
|---|---|---|---|
| T1 | Created 2026-10-31; milestone 4 | [#58](https://github.com/ShinningF1eld/RestaurantOS/issues/58) | None |
| T2 | Created 2026-10-31; milestone 4 | [#59](https://github.com/ShinningF1eld/RestaurantOS/issues/59) | None |
| T3 | Created 2026-10-31; milestone 4 | [#60](https://github.com/ShinningF1eld/RestaurantOS/issues/60) | None |
| T4 | Created 2026-10-31; milestone 4 | [#61](https://github.com/ShinningF1eld/RestaurantOS/issues/61) | None |
| T5 | Created 2026-10-31; milestone 4 | [#62](https://github.com/ShinningF1eld/RestaurantOS/issues/62) | None |
| T6 | Created 2026-10-31; milestone 4 | [#63](https://github.com/ShinningF1eld/RestaurantOS/issues/63) | None |
| T7 | Created 2026-10-31; milestone 4 | [#64](https://github.com/ShinningF1eld/RestaurantOS/issues/64) | None |
| T8 | Created 2026-10-31; milestone 4 | [#65](https://github.com/ShinningF1eld/RestaurantOS/issues/65) | None |
| T9 | Created 2026-10-31; milestone 4 | [#66](https://github.com/ShinningF1eld/RestaurantOS/issues/66) | None |
| T10 | Created 2026-10-31; milestone 4 | [#67](https://github.com/ShinningF1eld/RestaurantOS/issues/67) | None |

All ten issues were published in prerequisite order on 2026-10-31 and assigned to
GitHub milestone number 4 (product M9). No uncertain or failed issue writes remain.
Use the mappings above on reruns; inspect existing bodies before proposing updates
and never duplicate this set. Creating these issues does not authorize closing
them or changing unrelated repository metadata.

## Planning validation

At draft creation, no application tests, Compose exercises, installations, or
migrations were run. Planning validation checks ordered dependency existence and
acyclicity, T1–T10 identity uniqueness, R1–R12 coverage, unchanged source fingerprint,
and complete body sections. These checks establish draft consistency only, not
implementation feasibility or acceptance. Publication verification additionally
confirmed exact reviewed bodies (with dependency link substitution), all ten
identity markers, open state and milestone 4 assignment via fetched issue records.
Before commit, Markdown trailing spaces were removed without changing design content or issue criteria. The source fingerprint above reflects that formatting normalization; the reviewed pre-normalization SHA-256 was 394DC5B7EE86003A6AEC1CD69DB0D427E8623ACC78611D2F8DB6DFBB4EA24E58.
