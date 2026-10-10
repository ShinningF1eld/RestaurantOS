# Milestone 7 issue #27 verification

Date: 2026-10-10 (Asia/Bangkok). Starting revision:
`4ff9aee89588952dd381db6bc1589506f8ebe967`, branch `milestone7`; initially clean.
Source: [issue #27](https://github.com/ShinningF1eld/RestaurantOS/issues/27),
[task T9](milestone-7-task.md), accepted [design revision 13](milestone-7-design.md)
and the roadmap. The live issue's old design path/revision 5 is historical;
revision 13 governs the current limiter behavior.

Status: measurements, operational documentation and real freshness/failure probes
are complete. Full ten-gate local validation passed; final PR CI remains required.
Full milestone acceptance is not claimed until all evidence below is complete.

## Scope and reproducibility

Production API behavior, response shapes, frontend code, dependencies, schema and
migration head are unchanged. Only benchmark tooling, benchmark unit regressions,
measured evidence, API/operational documentation and scoped artifact newline
attributes and exact public-checksum secret-scan exceptions change. The original
corrected uncached capture is reused, not replaced by the superseded first run.
All requests use normal Manager cookies, fresh tenancy/capability checks, live
stock and the real API/PostgreSQL/Redis path. No authentication bypass, test
control endpoint, production dashboard cache or speculative worker is introduced.

Versions 2.2.0/2.3.0 preserve the corrected seed and planner: one organization/restaurant,
four menus with 160 total items, four ingredients, 40 tracked recipe components,
an assigned Manager; 1,000 requests per cell after 50 excluded warm-ups, three
repetitions, concurrency 1/10/25/50. Mixes remain menu-list, menu-items,
20%/80% mixed reads, and mixed writes with 10% item PUT, 10% menu PUT, 80% item GET.
Nearest-rank latency and request-local SQL counting remain the measurement method.
Cold/warm runs cover the complete 48-cell workload. Supplemental physical
outage/restart cells select the same scenarios and concurrency cells without
changing sample counts, request plans or quotas.

The isolated settings loader now also supplies the benchmark-owned Redis URL,
ignoring developer dotenv/ambient Redis settings. Redis uses a random pinned
loopback port and nonpersistent container; Compose PostgreSQL and the allocated
`restaurantos_benchmark_*_test` database are disposable. Only five exact catalog
keys are cleared; no global Redis flush is used. API shutdown, database drop,
Redis removal and Compose cleanup must succeed before a result JSON is published.

Supplemental host inspection on 2026-10-10 identifies a 12th Gen Intel Core
i5-12400F (six physical cores, twelve logical processors), with Windows reporting
16,984,231,936 bytes of physical RAM (approximately 15.82 GiB). JSON retains OS/build,
processor identifier, logical count and available memory per capture, plus exact
Python/PostgreSQL/Redis/library versions and effective nonsecret settings.
The API and load generator run locally; disposable services run in Docker Desktop.
Docker server 29.6.2 reports Linux, twelve CPUs, 8,227,790,848 bytes of memory
(approximately 7.66 GiB) and the overlayfs storage driver. This inspection
describes the current host; the historical baseline's own runtime record is retained.
These serial measurements are not randomized paired samples or a deployment
capacity qualification.

Cache hits are validated payload reuse with no subsequent source-list reload;
the denominator excludes PUTs. Phase instrumentation separates authentication,
authorization, live recipe/stock, catalog source, analytics and remaining/write
SQL. SQL execution time includes driver/database wait and excludes application
calculation, DTO serialization and HTTP; it is not an additive latency percentile.
First-wave values distinguish initial cold fills from the full measured batch.
They follow the original methods; mixed-write concurrency one starts with a PUT,
so its first wave is not a dedicated read-fill probe.
The prototype's dashboard response checks validate 100 completed orders/2400 sales
today, average 24, and 700 completed orders over the seven-day graph on every call.

Commands, metrics, comparison validation and artifact retention are documented in
[the benchmark procedure](../testing/menu-read-benchmark.md). The comparison
report rejects seed/mix/sample drift, duplicate/missing cells, inconsistent errors,
the superseded baseline and inconsistent SQL/hit accounting. Summary percentiles
are medians of three repetition percentiles; raw repetition JSON remains retained.

## Measurement results

The full version 2.2 cold capture completed 48 cells/48,000 attempted requests,
with one `RemoteProtocolError` (0.002083% overall) in menu-items concurrency 10,
repetition three. That cell reports 999 instrumented responses and one unknown
SQL observation; no retry was made. Owned API/database/Redis/Compose cleanup
succeeded before its JSON was retained.
The full version 2.3 warm capture likewise completed all 48 cells/48,000 attempts,
with zero request errors and zero Windows idle-socket guard activations. Cleanup
succeeded and its unchanged JSON was retained. The guard's focused regressions
passed, but this capture did not reproduce that OS-level failure; its root cause
remains unproven. [The generated comparison](performance-milestone7.md) currently
contains complete warm/cold/outage/restart results against the corrected historical baseline.
The current-control capture is now complete: 48 cells/48,000 attempts, zero errors,
zero socket-guard activations and successful owned cleanup. Its [matched report](performance-milestone7-control.md)
shows warm median P95 improvements in three cells (1.0%, 1.6%, 8.4%) and
regressions in thirteen (1.0–82.7%). Some later control repetitions were markedly
faster; every repetition is retained. Identical observers/revision do not remove
serial environmental variation, so these are observed differences, not causal
or consistent latency gains. No full-milestone performance speedup is claimed.
The physical outage capture completed 18 cells/18,000 attempts with zero request
errors and successful owned cleanup: menu-list/menu-items/mixed-write at
concurrency 1/50, the original 1,000 attempts/50 warm-ups/three repetitions.
Redis stopped after the first warm-up and remained unavailable through the run.
Catalog hit ratio was zero; read SQL rates returned to six/seven. Mixed-write
concurrency-one median P95 was 139.08 ms, versus 25.43 ms historically and
44.23 ms in the warm capture: failed post-commit invalidation attempts have a
visible cost. Faster outage cells elsewhere do not establish an outage speedup,
given the observed serial environmental variation. Physical restart completed
the same eighteen selected cells/18,000 attempts, with zero errors and successful
cleanup. Each batch physically stopped Redis, performed an excluded real fallback
read, started Redis, checked readiness, waited the normal 5.1-second cooldown,
and removed only the exact catalog keys. First-wave fills, later TTL expiry and
occasional classified Redis fallback are retained in the final comparison.
All catalog measurements are complete. [The report](performance-milestone7.md) contains every required
historical-baseline comparison and the raw JSON hashes.
Historical/current application revision and observer differences must be disclosed;
latency changes cannot all be causally attributed to caching. No fixed performance
target or blanket speedup claim is introduced.

Against the corrected historical baseline, warm SQL rates fall by approximately
8.3–16.6% across the sixteen scenario/concurrency cells, with validated hit ratios
78.29–99.77%. Warm median P95s **regress by 14.0–90.2%**; cold median P95s regress
by 13.0–71.7%. Query savings therefore do not establish a latency improvement.
The current uncached control is still required to interpret application/observer
differences; serial captures cannot attribute every change to caching. All
repetition values, P50/P95/P99, SQL phase costs and first-wave fills are retained.

## Optional dashboard recommendation

Recommendation: **defer production dashboard caching**. Both live/prototype
captures completed twelve cells/12,000 attempts each with zero errors and every
financial response check passing. The [dashboard experiment](performance-milestone7-dashboard.md)
records ten live SQL statements versus about 6.006–6.009 per prototype response
(approximately 40% fewer), and 99.23–99.50% complete aggregate-cache reuse.
Median P95 improved by 20.0%, 2.6% and 11.3% at concurrency 1/25/50, but regressed
13.0% at concurrency 10. These serial observations remain local workload evidence,
not a deployment target or guaranteed gain. The evaluation adds a separate
historical dataset of 700 completed paid orders and 1,400 immutable item snapshots,
without altering the original menu-read workload. Its Redis prototype exists
only inside the benchmark process, caches four aggregate results after fresh
authorization and has a ten-second source-age bound. It deliberately has no
order-write invalidation and is not a production cache design. Potential query
savings do not approve stale completed-order reporting or independently aged
aggregate entries. The [real committed-delete probe](benchmarks/dashboard-freshness.json)
passed in both modes: Manager delete 403, Owner delete 204, then Manager reads
100 → 99 orders immediately when live, versus 100 → 100 with the prototype.
After 10.1 seconds both read 99 orders/699 seven-day orders, with stock unchanged
and exactly one transactional deletion audit. This establishes the measured
freshness tradeoff on the owned legacy fixture; no production freshness approval
or invalidation design is inferred.

Any implementation decision requires reviewed scope for coherent aggregate reads,
order completion/edit/deletion invalidation, report dates/timezones, permitted
freshness, tenant keys, recovery and representative deployment volume. AI endpoints
remain deferred; workers/events belong to Milestone 8.

## Operational contracts

[Catalog cache contract](../api/catalog-cache.md) and
[Redis runbook](../runbooks/redis-cache.md) document the ten-second absolute age,
post-commit targeted invalidation, PostgreSQL fallback, independent catalog/auth
circuits, 100 ms command budget, five-second probes, three auth recovery successes,
fixed-window quotas, ten-second leases/eight-second auth deadline, conservative
ambiguity handling and live local history during recovery/flapping.
Authentication API/runbook and Redis architecture link these contracts.

Local capacity is finite and rejects untrackable new keys with generic 429 and
Retry-After instead of evicting active history. The existing reproducible
[issue #25 allocation measurement](verification-milestone7-issue25.md) and auth
runbook establish the development 10,000-entry cap's allocation costs, not a
production capacity recommendation. No deployment exists; production sizing must
measure actual runtime/RAM/outage distinct keys/process count with overhead.
Per-process outage quotas, loss on API/Redis restart, lack of pre-outage history,
and weaker distributed-guessing protection are explicit accepted limitations.
No PostgreSQL shadow counters or auth cookie/session policy changes are made.

Documentation disagreement: the root engineering instructions' infrastructure-only
Redis/PostgreSQL-limiter note and ADR 0003's original limiter wording describe
the earlier implementation. Current application code, accepted design revision
13 and dated #24–#26 evidence implement Redis admission with stricter local
fallback. This issue documents that existing behavior; it does not expand auth
permissions or use historical plans as authorization for a production change.

## Acceptance and requirement mapping

| Issue #27 criterion | Evidence/status |
|---|---|
| Identical baseline versus cold/warm/mixed-write metrics | Passed: original corrected baseline plus full cold/warm/current-control captures, all percentiles/counts/hits/errors/environment/revisions retained |
| Physical outage/restart and live authorization/stock cost | Passed: real stop/start captures, separate SQL phase costs/first-wave fills, honest regressions/variation and #25/#26 correctness evidence |
| Tuning/staleness/fallback/limiter/recovery/memory/limitations | Documented in API/Redis/auth contracts and runbooks |
| Measured dashboard implement/defer recommendation | Passed: two 12,000-attempt captures and real committed-delete freshness probe; production cache deferred pending reviewed follow-up |
| Reproducible exit criteria and passing full evidence | Partially passed: complete local ten-gate run/probes/exit mapping passed; final PR CI remains required before milestone completion |

| Requirements | Correctness and operational evidence |
|---|---|
| R1 | #22/#23/#26 source-age/late-fill/invalidation races; ten-second contract |
| R2 | Warm-hit tenant isolation, revoked membership/assignment, resource/capability regressions; authorization remains live |
| R3 | Live receipt/waste/count/consumption/recipe reads and authoritative order price/stock regressions |
| R4 | Classified failure/corruption fallback, circuit bypass/single probe, committed-write invalidation failure and physical outage/restart |
| R5/R6 | Real Redis/local atomic admission, ambiguity, leases/deadline, physical restart, two processes, memory pressure, flapping/recovery regressions |
| R7 | Original corrected baseline, cache comparisons, reproducible report and full gate evidence |
| R8/R9 | Failure-only login, normalized HMAC pair/IP keys, dummy verification, generic 429, separate refresh accounting regressions |
| R10 | Safe transition/probe/invalidation events, secret redaction and diagnostics regressions; runbook describes inspection |

| Roadmap exit criterion | Evidence/status |
|---|---|
| Cache correctness/invalidation tests pass | Passed locally: fresh full integration/browser gates include existing #22/#23/#25/#26 regressions and deterministic races; final PR CI pending |
| Benchmarks reproducible from scripts | Passed: complete real captures/probes, versioned runners, report validation, raw JSON/checksums and exact commands |
| README claims only measured results | Passed: query savings, P95 regressions and observed variation link directly to retained measurements; no consistent speedup/capacity claim |

## Validation, failures and resource cleanup

Benchmark unit tests and comparison validation regressions passed: 26 tests,
including existing workload/ambient settings/failure/warm-up/atomic-write tests,
new reset ordering/GET-only hit denominators, error/unknown SQL accounting and
eleven report-validation tests.
Two additional cases verify that the Windows pool guard expires only error
10038, propagates other OS errors and restores the original function on exit.
Command from `backend/`:

```powershell
.venv-m6-dev/Scripts/python.exe -m pytest tests/unit/test_menu_read_benchmark.py tests/unit/test_menu_read_report.py -q
```

The first sandbox unit invocation could not create Windows asyncio's internal
loopback socketpair; the same network-blocked tests passed outside that sandbox.
The initial 20-request real warm smoke passed eight cells with zero errors and
removed all owned resources; it is harness evidence, not a percentile baseline.
An initial full warm attempt failed in a mixed-read cell, cleaned its owned
resources and emitted no artifact. A standalone reproduction of that cell passed.
Safe per-status failure diagnostics were added before rerunning the full workload.
Failed/partial rows are never substituted for a complete successful capture.

The version 2.0 full warm capture succeeded with all 48,000 requests and is
retained with its exact source snapshot and a separate comparison. It reduced
SQL queries but its P95 latencies regressed against the historical capture.
A subsequent threaded cold attempt failed in its first-repetition mixed-write
concurrency-50 cell (999 successful responses, one transport error); its owned
resources were removed and no partial artifact was published. Neither failure's
root cause is proven. Version 2.1 separates API and generator processes while
retaining the 30-second HTTP timeout, five-second keep-alive, workloads and quotas;
it also records safe transport exception classes. A real subprocess smoke passed
eight cells/160 requests with zero errors. The dashboard prototype smoke passed
40 response financial checks with six SQL statements per response.

The full version 2.1 cold attempt also stopped after 41 successful cells on one
`ReadError` among 1,000 mixed-read requests at concurrency 10, repetition three.
Cleanup succeeded and no partial JSON was published; process separation did not
eliminate that intermittent failure. The cause remains unproven. Version 2.2
therefore records complete runs with their actual error rates, including failed
attempts in HTTP percentiles and identifying lost-response SQL work as unknown.
SQL/cache metrics use instrumented responses only. No timeout relaxation or
automatic retry masks those errors. Incomplete attempts are disclosed separately;
success means measurement and cleanup completed, not zero request errors.

The first version 2.2 warm attempt stopped after two successful cells on a Windows
`OSError` inside HTTPcore's idle pooled-socket readability check, before HTTP
dispatch. Its numeric OS error code was not logged; the exact code is not claimed
as established. Owned cleanup succeeded and no partial JSON was published.
Version 2.3 narrowly handles `WinError 10038` at that descriptor check as an
expired socket, matching the existing missing/negative-descriptor behavior.
Other OS errors propagate with safe numeric diagnostics. Runtime metadata counts
these guard activations; actual HTTP failures are retained without retries.
The completed cold capture and its exact 2.2 source are preserved; subsequent
matched warm/control and supplemental captures use 2.3. No production/dependency,
pool sizing, timeout, keep-alive, sample, quota or cache-clock change is made.

`scripts/verify-menu-benchmark-cleanup.py` passed all three real injected failures
(seed, measurement, HTTP request) under hostile ambient settings: expected exit 1,
no result/temp artifact, no allocated benchmark database or new owned Redis,
and an unmigrated connection-template database. Its own Compose project was
removed after those checks. This was repeated successfully with final version
2.3 after all captures/freshness checks. Full repository validation passed.

The first freshness-helper attempt incorrectly used the assigned Manager for
hard deletion. The API correctly rejected that Owner-only operation, cleanup
succeeded and no freshness artifact was emitted. The corrected probe verifies
Manager denial, uses a separate normal Owner cookie session for the committed
delete, and keeps the dashboard reads in the original Manager session. Production
permissions are unchanged.

The first full ten-gate attempt stopped at the baseline secret scan after locked
installation. Twenty-five high-entropy findings were individually checked against
public Git revisions and recorded source SHA256 values in the retained JSON and
dashboard report. Exact filename/value entries are marked reviewed false positives
in `.secrets.baseline`; its original entries, every detector/threshold/filter and
the raw captures remain unchanged. No file-wide or checksum-wide exclusion was
added. Full ten-gate validation with locked installation was restarted afterward.

Final full command from the repository root (exit 0, 2026-10-10):

```powershell
./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
```

| Gate | Result |
|---|---|
| baseline | Passed: Compose config, dependency integrity and candidate secret scan |
| backend-static | Passed: Ruff lint/format and mypy |
| frontend-static | Passed: ESLint, Prettier and strict TypeScript |
| backend-unit | 225 passed; isolated pure tests |
| backend-integration | 223 passed against real migrated PostgreSQL/Redis, including live access/stock, races, rollback, admission ambiguity and physical recovery/process tests |
| frontend-tests | 10 client + 12 component tests passed |
| frontend-build | Production Next.js build passed |
| migrations | Clean unique-head upgrade, seeded legacy preservation, Alembic drift checks and history-protecting downgrade refusal passed |
| browser | 26 Chromium workflows passed against the real API/production frontend, including warm catalog/current stock and limiter outage/recovery; auth traces disabled |
| image | Nonroot runtime build/smoke passed; no baked secrets; connection to disposable PostgreSQL passed and startup did not migrate |

No gates were skipped and locked installation was enabled. Additional manual
Ruff lint/format checks passed for all five benchmark/report/probe scripts.
The full log is retained locally at `test-results/issue27-full-validation-final.log`;
generated logs/builds remain ignored. Locked `npm ci` reported the existing six
high-severity dependency advisories; dependencies/locks were not changed, and
this passing gate run is not a new dependency-security assessment.

Final evidence/provenance checks also passed: original baseline SHA256 unchanged;
all captured runner/prototype/probe and comparison-report artifact hashes match;
204,000 final attempted requests, one cold transport error and one unknown SQL
observation. All detector/filter settings and original reviewed scan entries are
unchanged. A final `scripts/validate.py --gate baseline --no-install` passed
after evidence updates, and `git diff --check` passed. That partial follow-up is
additional candidate evidence, not a replacement for the complete run above.
Docker/browser/process inspection found only the two preserved developer
containers, no `.m6-browser-*` copies and no owned Python/Node API/frontend test
processes. No application database operation was performed.

## Remote evidence and database boundaries

GitHub issue #26 is closed as completed, but its retained pre-commit report and
current-state/roadmap still record final PR CI as pending. A live connector lookup
on 2026-10-10 returned no PR-triggered workflow runs for current revision
`4ff9aee89588952dd381db6bc1589506f8ebe967` and no legacy combined statuses.
The wrapper filters to PR events, so this is not absence of all CI. A separate
unfiltered Actions lookup verified [push run 38034397930](https://github.com/ShinningF1eld/RestaurantOS/actions/runs/38034397930)
on that exact starting commit: all ten `M6 / <gate>` jobs and `Milestone 6 acceptance`
completed successfully (2026-10-10, 07:25–07:29 UTC). This verifies issue #26's
committed code on push; its live verification instructions explicitly require
"a complete remote PR CI run" as well. Issue state alone cannot substitute for
that missing event, and the starting push does not test issue #27's new tooling.
Final PR CI must verify the final
candidate; the existing required `Milestone 6 acceptance` aggregate and complete
ten-gate policy remain unchanged.

Repository Alembic head remains `e68d9a24b537`; there is no new migration. The
application database is not queried/migrated by these measurements or validation.
Its last recorded revision is `c48b7e02f315`; this historical record is distinct
from repository head and is not a new inspection of its actual revision.
No deployment/cutover is claimed. Milestone completion must wait for all required
local/remote evidence; no historical approval substitutes for publication authority.
