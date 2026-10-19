# Milestone 8 issue #41 verification

Reviewed: 2026-10-19 (Asia/Bangkok). Sources: [issue #41](https://github.com/ShinningF1eld/RestaurantOS/issues/41),
[T11 criteria](milestone-8-task.md), authoritative [design revision 1](milestone-8-design.md),
ADRs 0001/0002, current event/analytics/alert contracts and operational/testing runbooks.
Base: `88eee5483838f531e446969e731a34d2dcbeee29`, initially clean worktree.
Scope: uncommitted measurement harness, timing unit regressions, required harness
static checks, retained benchmark/operational evidence, exact reviewed metadata
false positives in `.secrets.baseline`, and M8 documentation.
No runtime business, schema, HTTP/UI, retry policy or dependency change.
Review follows the `review-verify` skill; it is the implementing agent's review,
not an independent review or remote CI. No commit, push or GitHub state change.

## Acceptance review

Final inspection found no actionable defect in the new measurement/gate change.
Criteria 1–4 and 6 pass their **evidence requirements**. This does not mean the
five-second performance target passed: documented real misses are the principal
operational finding below. Criterion 5 cannot be fully accepted without complete
final PR CI; the task must remain uncommitted, so that evidence is untested.
No M8 completion is claimed from local measurements or historical slice results.

| Issue criterion | Result | Evidence |
|---|---|---|
| 1. Reproducible dataset/load/environment/tuning/revision, P50/P95/P99 and target misses | Passed (execution/inspection) | Five retained serial cells, all eight event types/three production consumers, exact commands and source fingerprint. Monotonic commit/visibility bounds avoid transaction-timestamp undercounting. Four timing/statistic unit regressions pass. |
| 2. Honest per-consumer outcomes, misses, backlog/age/retries/failures/storage/stream and UI distinction | Passed (execution/inspection) | All 1,980 effects complete; full raw samples and tables include proven versus uncertain misses, 60-second tails, peak backlog/age and retained counts. No earlier comparable M8 baseline exists, so no regression claim is made. UI cadence and outage limits remain explicit. |
| 3. Actual safe CLI recovery, shutdown, Redis loss and maintenance | Passed (execution) | First retained cell includes status/inspect/repair/replay before/after JSON, original/replay identity, DB role, analytics unchanged, forced command exit and graceful zero exit, owned stream deletion/reconstruction. Every cell runs initialize/rerun/rebuild/reconcile; full gates additionally prove exact in-flight deaths, physical Redis restart, real poison retries and backup/restore/baselines. |
| 4. Current selected contracts/settings and rollout/retention/deferred boundaries | Passed (inspection/execution) | API/architecture/worker/testing docs updated and linked; complete worker settings retained. Maintenance runbook still requires stopped writers/workers and verified backup. No production deployment, external delivery, pruning, tracing or dashboard-projection cutover claim. |
| 5. R1–R14/three exits, current full local gates and final complete PR CI | Passed locally; Untested final PR CI | Dated evidence map below and all ten locked-install local gates pass. No commit/push/PR is authorized, so complete final PR CI under `Milestone 6 acceptance` is unavailable. Criterion remains open. |
| 6. Application revision/cutover distinct, omissions/risks and scoped documentation | Passed (inspection) | Repository/disposable head recorded; no application revision inspection or operation claimed. Target misses, small synthetic dataset/observer overhead, single light cell and untested CI are explicit. Older unrelated auth/M7 historical evidence is not re-verified by these edits. |

## Measurement and operator commands

All five exact commands are in
[the reproduction procedure](../testing/event-freshness-benchmark.md). Each
returned 0; reports were copied unchanged into `docs/milestone8/benchmarks/` and
audited for exact event mix, unique subscription samples, effect/receipt counts,
zero final pending/retry/failure counts and the current script SHA256.
The [measured report](performance-milestone8.md) derives tables from those samples;
all original repetitions are retained. Performance source/settings were unchanged
between cells. Only offered rate/bundle count and the pressure drain watchdog vary.

Development smoke checks initially exposed missing ORM registration and a seeded
order-ID/sequence collision in the new harness. Both were corrected in the
measurement script; the final smoke with operator rehearsal and all five retained
cells passed. These were fixture/setup failures, not production worker changes.

The first full cell retains event `d7625af4-ee35-4750-a758-4120ce8d45ca`, failed
sink delivery `d9bcc281-e8a2-4dc6-85da-71933ba980d1`, original correlation
`operations-0bf728f95fb946eea379aee4d6ca27d1` and replay
`c4f70541-dc13-4ce0-b02f-09c9d48791b4`. The sink has one old failed attempt and
one successful attempt in cycle 1; analytics stays at one successful attempt in
cycle 0. Replay provenance is authenticated DB role `restaurantos`, with a
recorded reason and safe JSON omitting its free-form text. Stream size changes
415 → 0 at owned-key deletion and reconstruction completes the selected delivery;
forced exit is 1, recovery graceful exit is 0. This queued/startup command kill
does not stand in for the full suite's precise in-flight crash barriers.

## Evidence map

The following suites are required by the unchanged shared gates, rather than
optional worker checks. The dated final local gate result below determines their
execution status; historical slice reports explain the already implemented
boundaries but do not substitute for current execution.

| Design requirement | Executable evidence and earlier design context |
|---|---|
| R1 atomic committed facts | Producer event/delivery/audit failure injection in `test_event_producers.py`, inventory/order transaction suites; [T3](verification-milestone8-issue33.md). |
| R2 stock/money/permissions/idempotency | Order inventory/tenancy suites, lock-proven overlapping acceptance and stock changes, no-restock cancellation; [regression map](../testing/milestone8.md). |
| R3 recover committed work | Actual API death matrix, worker before/after commit barriers, relay/ACK ambiguity and physical Redis restart in producer-process/execution/worker suites; [T10](verification-milestone8-issue40.md). |
| R4 duplicate-safe effects | Unique effects/receipts, concurrent duplicate locks, analytics daily-row overlap and alert/stub timing tests in analytics/alerts/execution suites. |
| R5 failure isolation/eight attempts | Execution unit/integration suites, real-clock poison restart, default eight attempts, persisted due state, shared-outage refund, unsupported contracts and fencing. |
| R6 safe operator recovery | Actual CLI redaction/replay tests plus #41 `--operations` JSON: failed inspection, repair, original event/correlation, new replay UUID and analytics remaining at one attempt. |
| R7 correct daily sales | Exact SQL reconciliation, tombstones/deletion permutations, queued watermarks/rebuild and shared-row overlap; #41 CLI reconcile before/after maintenance. Dashboard remains live SQL. |
| R8 truthful episodes | Inventory boundary/revision/close-before-open/new-episode and immutable history regressions; production inventory creation and alert projection in measured workload. |
| R9 stubs/diagnostics | Alert projection tests prove stale skips, baseline suppression and stock-lock timing; #41 checks one stub per new episode and six diagnostics per bundle. |
| R10 scoped reads/UI | Alert-read isolation/assignment/revocation tests; inventory components and real Chromium API/worker journeys. |
| R11 correlation/inspectability | Contracts, safe logging/CLI tests, original/replay identities and database-role provenance retained in #41 JSON. No payloads or credentials in retained report. |
| R12 measured freshness/UI cadence | [Method and commands](../testing/event-freshness-benchmark.md), [dated measurements](performance-milestone8.md), timing interval/percentile unit tests; 15-second UI cadence separately verified by component/Chromium suites. |
| R13 safe initialization/retention | Maintenance/analytics/alerts suites and clean/seeded backup/restore migration rehearsal, downgrade guards; #41 CLI initialize/rerun identity and rebuild/reconcile with stopped writers/workers. |
| R14 full validation/documentation | All ten local gates, cleanup probes and dated reports; final complete PR CI remains untested. |

| Roadmap exit criterion | Evidence boundary |
|---|---|
| No silently lost committed event under tested failures | Cross-feature API-death worker effects; ambiguous publication/ACK, consumer commit crashes, Redis-loss reconstruction and matching final subscribed receipts. Claims apply to tested boundaries only. |
| Duplicate delivery does not duplicate analytics/notifications | Concurrent/after-commit duplicate receipt tests, analytics delta/revision/tombstone suites, unique per-episode stub/diagnostic effects and reconciliation. |
| Safe failed-work inspect/replay | CLI auth/redaction/selection tests; real poison eight-attempt recovery and #41 retained per-consumer repair/replay transcript. |

## Local validation

```powershell
./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
```

Passed with exit 0 and `PASS: full validation` on 2026-10-19. The command installs
the committed Python hashes and npm lock and runs every shared gate. Full log:
`test-results/issue41-full-validation.log`. The implementation source was final
before this run; measurement output and documentation were completed afterward.
The final candidate-file baseline scan/diff checks are recorded separately below.

| Gate | Outcome |
|---|---|
| baseline | Passed: locked installs, Compose config, pip integrity and candidate-file secret scanning. |
| backend-static | Passed: Ruff lint/format, mypy (163 application sources), four harness files including the new measurement script. |
| frontend-static | Passed: ESLint, Prettier, generated Next route types and TypeScript. |
| backend-unit | Passed: 298 cases, including four timing/percentile regressions; no services. |
| backend-integration | Passed: 333 cases in 582.83 seconds, real PostgreSQL/Redis/processes, then no Alembic drift. This includes actual in-flight crashes, real-clock poison/restart and physical Redis restart. |
| frontend-tests | Passed: 10 client and 19 component tests. |
| frontend-build | Passed: isolated production Next.js build. |
| migrations | Passed: unique clean head, seeded legacy preservation, backup/restore and actual initialization/rerun/rebuild/reconcile, retained stock/event/replay/history guards and model drift. |
| browser | Passed: 29 production Chromium/API/worker workflows in 3.9 minutes; required intended-failure cleanup probe returned its expected failure and verified complete owned cleanup. Auth traces remain disabled. |
| image | Passed: locked nonroot runtime contents, liveness/disposable PostgreSQL connectivity, startup without migration, owned cleanup. Image unchanged. |

Existing framework/naive-UTC deprecation warnings remain; no production change
was introduced to silence them. No local gate was skipped. No CI workflow,
required-check name or enforcement policy changed. Final complete PR CI under
`Milestone 6 acceptance` remains untested.

Final artifact verification:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --no-install
git diff --check
```

The final artifact baseline recheck passed (exit 0, explicitly partial), log
`test-results/issue41-final-baseline-recheck.log`. Its first attempt returned 1
because each retained JSON's repository SHA, script SHA256 and Alembic revision
matched the hex-entropy detector (15 findings). Each value was inspected as
non-secret metadata; `.secrets.baseline` adds exactly those 15 per-file/value
entries with `is_secret:false`. Prior entries, detectors, thresholds and filters
remain unchanged. Raw measured JSON was preserved byte-for-byte. The failed
initial scan is retained in `test-results/issue41-final-baseline.log`.
The diff whitespace check passed; only the existing CRLF-to-LF advisory on the
edited architecture document appears. These post-output checks supplement the
successful full locked-install run, not replace it.

Final cleanup inspection found no retained containers in any of the nine
issue-41 Compose projects observed in the retained validation/smoke/measurement
logs, and no remaining RestaurantOS `-m app.worker` process. Allocated database
contexts assert their drop; full normal/injected-failure cleanup probes passed.
HEAD is still the comparison base and all changes remain uncommitted.

## Publication and CI follow-up (2026-10-19)

After the measurement review above, the user authorized committing/pushing a
new branch and verifying CI before production optimization. Commit `58f043d`
publishes the measured baseline on `codex/m8-issue41-evidence` in
[draft PR #53](https://github.com/ShinningF1eld/RestaurantOS/pull/53).
The original report's uncommitted/untested-CI statements describe its earlier
measurement-time snapshot; current publication/check results belong to this
follow-up and the PR's current-head checks.

[Initial PR CI run 140](https://github.com/ShinningF1eld/RestaurantOS/actions/runs/39233534423)
passed nine gates and failed browser (28 passed, one failed), so the unchanged
`Milestone 6 acceptance` aggregate correctly failed. `alerts.spec.ts` expected
history `resolution_reason=stock_recovered`, but the value remained null when
the general 15-second assertion budget expired. This is consistent with the
already measured 60-second recovery tails; the CI artifact has no worker trace
to identify the precise cause of that instance.

The test-only follow-up assigns 90-second budgets specifically to the four
worker-projection polls in the three alert workflows, allowing the existing
60-second pending/stall recovery plus relay/processing. Each workflow's total
budget retains its original 60 seconds for other work plus the explicit
projection allowances (two for the first case, one for each other case).
All expected values, UI refresh/error/form/access assertions, normal assertion
timeouts, zero Playwright retries, production worker settings and five-second
benchmark target are preserved. The performance finding above remains open;
this change does not claim to fix production freshness. Installed Next.js
Playwright guidance was consulted before the frontend test edit.

The follow-up uses this affected-gate command (explicitly partial); its local
outcome and complete new-head CI outcome are reported on PR #53:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --gate frontend-static --gate frontend-tests --gate browser --no-install
```

The browser gate includes a production build, every normal workflow and the
required intended-failure cleanup probe. No gate, expected condition or aggregate
enforcement is removed. The new-head full CI run is required before claiming a
passing published baseline.

## Operational finding: five-second target misses with unchanged defaults

This is an observed limitation of the base worker, not a regression introduced
by the measurement. At 0.5 bundles/s, pooled P95 upper bounds across the original
three runs are 16.268 seconds (analytics), 18.168 (alerts) and 17.352 (sink).
The sink maximum is 73.511 seconds. All work drains with correct unique effects,
zero charged retries and zero failed deliveries. "Healthy" means available
dependencies; it does not mean adequate processing capacity or target compliance.

The [safe correlated trace](benchmarks/paced-2-tail.json) records a sink reference
finding `delivery_missing_or_busy`, followed by publication/processing about 61
seconds later. Its real commit latency is bounded at 72.336–72.454 seconds.
The default 60-second pending/stalled-publication budgets in
`backend/app/core/config.py` and the busy-reference/recovery paths in
`backend/app/modules/events/worker/runtime.py` are consistent with that tail.
The trace proves the busy result and later recovery; it does not by itself prove
which competing transaction held the delivery lock.

Impact: derived state can lag well beyond the five-second target without a
dependency outage or poison failure. Status `retries:0` counts charged event
retries and must not be read as proof that no Redis reference was delayed.
Before relying on that target, a separately scoped performance change should
measure relay capacity and bounded earlier revisits of busy references while
preserving fencing, due times, uniqueness and outage policies. #41 deliberately
records misses with unchanged tuning, as its criteria require; it does not
silently change retry/recovery semantics to obtain a passing benchmark.

## Database and completion boundary

Repository migration head remains `c3d8e1f52a74`; the measurement records the
revision of its freshly migrated disposable database. No application revision
inspection, application migration, cutover, initialization or rebuild was run.
The actual application revision is not inferred from repository head, test
databases or historical incident evidence. Application operations still require
the [maintenance runbook](../runbooks/event-maintenance.md), stopped writers/all
workers and verified backup/restore.

Final PR CI under unchanged `Milestone 6 acceptance` is untested because no
commit/push/PR was authorized. This prevents full criterion 5/M8 acceptance even
if every local gate passes. External notifications, deployment, full tracing,
broader metrics/timezones, online cutover and retention pruning remain deferred.
