# Milestone 7 menu-read benchmark

`scripts/benchmark-menu-reads.py` measures the real authenticated HTTP request
path for the two Milestone 7 catalog reads. The historical version 1.1 baseline
measured the uncached PostgreSQL implementation. Version 2.3
reuses that seed, planner, HTTP path and nearest-rank method for measured Redis
comparisons. The corrected uncached artifact already exists and is retained;
do not substitute the superseded version 1.0 capture.

## Reproduce

Requirements: the supported Python environment with the locked backend dev
dependencies installed, and a reachable PostgreSQL server whose role can create
and drop databases. Set only the connection template in `TEST_DATABASE_URL`;
the value must use an allowed local/test-service host and name a PostgreSQL
database ending in `_test`. The repository's test Compose service uses temporary
storage and a random loopback port.

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5433/restaurantos_test" # pragma: allowlist secret
& .\backend\.venv-m6-dev\Scripts\python.exe .\scripts\benchmark-menu-reads.py
```

Since version 1.1.1 the harness constructs application settings explicitly with ambient settings
sources and dotenv disabled, including parsing of malformed inherited JSON:
declared application defaults plus benchmark overrides (development pooling,
WARNING logging, SQL echo off, localhost trusted origin and nonsecure local
cookies). Migrations, seed and API use identical validated settings; version 2.1
and later deserialize them in the separate API process. Caller auth,
database, environment and logging settings cannot override it; `DATABASE_URL`
is never a fallback. Only `TEST_DATABASE_URL` selects the guarded connection
template. Effective nonsecret settings are recorded in the JSON runtime metadata.
`scripts/test_support/disposable_postgres.py` validates the template, allocates
a random `restaurantos_benchmark_*_test` database, and drops only that generated
database in a `finally` block. Alembic, deterministic seed operations, the API,
and all benchmark requests target the allocated database. The supplied template
database is never migrated, truncated, seeded, or dropped. Use
`--inject-failure-after seed`, `--inject-failure-after measurement`, or
`--inject-failure-after request` to exercise
nonzero failure and cleanup paths; these test-only switches are hidden from the
normal help output. The request injection sends a real authenticated request to
a missing menu during measurement, exercising explicit injected-failure rejection even
with `--warmup 0`.

For a short harness smoke run, reduce the workload explicitly:

```powershell
& .\backend\.venv\Scripts\python.exe .\scripts\benchmark-menu-reads.py `
  --requests 20 --warmup 2 --repetitions 1 --concurrency 1,2
```

Defaults are 1,000 measured requests, 50 excluded warm-up requests, three
repetitions, concurrency levels 1/10/25/50, and all four scenarios. These
settings are configurable with `--requests`, `--warmup`, `--repetitions`,
`--concurrency`, and `--scenarios` (comma-separated scenario names).

## Deterministic workload

Each fresh database contains one organization, one restaurant, one Owner
membership, one Manager membership assigned to the restaurant, four menus, and
40 items per menu (160 total). The authenticated benchmark principal is the
assigned Manager, so reads include branch-scoped authorization. Four inventory
ingredients each start with 5,000.000 g. Ten items in each menu (40 total, 25%)
have one 25.000 g recipe component and inventory tracking enabled; the other
items are untracked. Names, descriptions, prices, amounts, and item/menu ordering
are fixed. Database IDs and login credentials are generated only inside the
disposable run. The workload state is newly seeded on every run.

| Scenario | Request mix |
|---|---|
| `menu-list` | 100% `GET /restaurants/{restaurant_id}/menus` |
| `menu-items` | 100% `GET /menus/{menu_id}/items`, round-robin across four menus |
| `mixed-read` | 20% menu-list and 80% menu-item list |
| `mixed-write` | 80% menu-item list, 10% item update, and 10% menu update |

The mixed-write sequence has a ten-request cycle: one item PUT, one menu PUT,
then eight item-list GETs. This is exactly 10%/10%/80% over complete cycles;
short custom request counts may contain a partial cycle. Warm-up requests advance
the same sequence, so the measured sequence starts at the configured warm-up
offset. The sequence is fixed and can be run after caching is introduced to
compare read behavior while catalog edits occur. HTTP status and query-count
instrumentation are checked. Any non-2xx response or transport error makes the
entire benchmark fail with a nonzero exit and no result artifact. All measured calls use the normal
login cookies, auth middleware, current tenancy checks, catalog service and
response serialization. Warm-ups use the same endpoint mix and are excluded from
latency and query totals. Repetitions restart each scenario's deterministic
request index.

The isolated API uses the normal development connection pool settings for its
single long-lived server loop. The disposable database is still selected
explicitly through the generated `DATABASE_URL`; test mode's `NullPool` is not
used because it exists to isolate TestClient's independent event loops.

## Metrics and artifacts

Latency is client-observed HTTP duration. P50/P95/P99 use nearest-rank percentiles.
PostgreSQL queries are counted with SQLAlchemy's `before_cursor_execute` event
inside per-request ASGI context. The response-local query counter includes SQL
executed for auth, tenancy, catalog and live availability in that request;
migration, seed, login, server health and warm-up SQL are excluded from measured
totals. The report records total SQL statements and average queries per measured
request. For this baseline, `cache_hit_ratio` is null and its label explicitly
says `N/A`.

The console prints one line per scenario/concurrency/repetition. A successful run
atomically writes a versioned JSON result under `artifacts/benchmarks/`; generated
results are git-ignored. Each result includes the source commit, script version,
configuration, Python/library/PostgreSQL versions, host/CPU/memory where
available, dataset, request mixes, measurement method, timestamps, and per-run
metrics. Runtime credentials and raw authentication identifiers are not included.
The historical version 1.1 baseline accepted a run only when all measured requests succeeded, the API
stops, and disposable database cleanup succeeds. If cleanup fails after the atomic
artifact write, that artifact is removed. Failed runs leave no JSON, including
transport failures whose database query count cannot be known. Version 2.2's
complete-capture error/SQL-observation policy is documented below. Use an existing
successful artifact only after checking version compatibility and matching its
configuration and workload.
The original `schema_version`, `cache_mode`, `cache_state`, and nullable cache-hit field
are intended to hold later cached results in the same shape. Cold/warm cache
states are not applicable before Redis caching exists. For the later comparison,
record a cache-cleared cold fill separately from warm hits, while retaining the
same request mix and run configuration; keep the exact command and JSON artifact
and match dataset, scenario, concurrency, repetitions and request counts.

## Baseline evidence versions

The initial version 1.0.0 artifact
`menu-read-baseline-20261007T120114Z-75f7ad6d.json` is superseded: its actual
mixed-write workload was 40% writes/60% reads while its metadata claimed
20%/80%, and it did not isolate all settings. Do not use it for the future cached
comparison. Version 1.1.0 corrects the cycle, configuration and failure policy.
The full corrected capture uses version 1.1.0 at `aa01cde`; version 1.1.1 further
disables ambient settings-source parsing during setup. It preserves the measured
request path, workload, percentile method and effective settings of that capture.
The final loader's real smoke verifies identical effective settings, so the full
1.1.0 capture remains the comparison baseline. The smoke is not a replacement
latency baseline.
See the [Issue #20 verification](../milestone7/verification-milestone7-issue20.md) for the
corrected capture and validation evidence.

## Recorded comparison evidence

The [recorded latency baseline](../milestone7/verification-milestone7-issue20.md#recorded-latency-baseline)
preserves all 48 measured P50/P95/P99 cells and PostgreSQL statement totals in
tracked documentation, together with the method for comparing cached results.
Use both latency and query counts when assessing the cached version.

## Dashboard caching evidence

Use the baseline and post-cache artifacts to decide whether dashboard caching is
worth a separate design. At minimum, compare dashboard endpoint P50/P95/P99 and
query count at the same concurrency with and without cache, including the source
query shape, authorization cost, data freshness requirements, and behavior after
underlying order/inventory changes. This benchmark intentionally does not call the
dashboard endpoint, so it does not claim evidence for or against dashboard cache
implementation.

## Issue #27 reproduction

Use Python 3.12 with the committed development lock, Docker Desktop, PostgreSQL
16 and Redis 7. `--isolated` allocates the validation runner's unique disposable
Compose project; the benchmark additionally owns a nonpersistent Redis container
with a random pinned loopback port for physical stop/start. No developer database,
Redis service, configuration or volume is used. Without `--isolated`, only the
guarded explicit `TEST_DATABASE_URL` is a connection template; Redis is still
separately allocated. All application settings are explicit, including the owned
Redis URL; ambient `REDIS_URL` and dotenv are ignored.

The original full workload is unchanged: 1,000 measured requests, 50 excluded
warm-ups, three repetitions, all four request mixes, concurrency 1/10/25/50.
Use the existing corrected JSON as the baseline, then run:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-menu-reads.py --isolated --cache-state warm --output-dir artifacts/benchmarks/issue27
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-menu-reads.py --isolated --cache-state cold --output-dir artifacts/benchmarks/issue27
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-menu-reads.py --isolated --cache-state outage --scenarios menu-list,menu-items,mixed-write --concurrency 1,50 --output-dir artifacts/benchmarks/issue27
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-menu-reads.py --isolated --cache-state restart --scenarios menu-list,menu-items,mixed-write --concurrency 1,50 --output-dir artifacts/benchmarks/issue27
```

Warm cells clear their five exact catalog keys before warm-up. Cold cells also
clear immediately after warm-up, retaining the measured request-index offset.
Cold describes the **initial state of a batch**, not a forced miss on every call.
Natural ten-second TTL expiry, concurrent fills, normal command deadlines,
post-commit invalidation and mixed writes remain enabled. First-wave percentiles
and hits are recorded separately so cold-fill costs do not disappear in 1,000
requests. No test clock override or production cache-control endpoint is used.
The first wave follows the original request planner and can include PUTs; at
mixed-write concurrency one it starts with a PUT, not a dedicated cache-fill GET.
Outage stops the owned Redis after the first warm-up and leaves it unavailable
through the remaining cells. Restart physically stops/starts the nonpersistent
container before each measured batch and permits the normal recovery cooldown;
measured reads must refill lost catalog entries. These supplemental runs retain
the baseline's sample count, warm-up, repetitions and selected concurrency cells.
They measure catalog behavior; issue #25/#26 regressions prove auth recovery,
flapping, process restart and cookie safety.

Version 2 adds benchmark-only request-local headers. Validated payload reuse is a
hit only if no source-list reload follows it. The denominator is catalog GETs,
excluding PUTs; dashboard experiments count their own aggregate-cache reuse.
SQL counts/timings are attributed to fresh authentication, authorization,
live recipe/stock, catalog source, analytics and remaining/write operations.
These nonoverlapping SQL timings include driver/database waits and exclude
Python calculations, serialization and HTTP; do not add them to HTTP percentiles
or infer that authentication/authorization could safely be cached.

Generated JSON is schema 2 and records application revision, dirty state,
script SHA256, exact settings, runtime/hardware, complete per-cell metrics and
complete request outcomes. Instrumentation is confined to the benchmark process
and does not modify application code. Missing instrumentation, no observable
responses, failed warm-up, cleanup failure or injected failure exits nonzero
without a complete artifact.
Final JSON is written only after API, database, Redis and Compose cleanup.

Version 2.1 separates the API subprocess from the load-generator interpreter;
the earlier harness shared one Python interpreter between its HTTP client and
API thread. Frozen validated settings are passed in private runtime environment
IPC, never written to artifacts or command-line arguments. The child disables
ambient settings sources and performs no migration. Graceful stdin shutdown and
engine disposal must succeed; forced termination rejects the capture. Windows
starts the child without a visible console. Request timeout remains 30 seconds,
Uvicorn keep-alive remains five seconds, and workloads/quotas/cache clocks do not
change. Transport failure categories include the safe exception class.

The original historical capture remains the requested baseline, but latency
differences also include observer/topology/application changes. A retained full
version 2.0 threaded warm run and its source snapshot document the initial
regressions; failed threaded attempts were discarded and are disclosed in the
verification report. Use the matched version 2.3 uncached control to interpret
current caching costs; neither comparison alone establishes deployment capacity.

Version 2.2 retains measured HTTP/transport errors in a **complete** capture,
without retries, rather than repeatedly selecting error-free runs. Percentiles
include every attempted request. Instrumented responses supply SQL/cache costs;
lost responses have unknown server work, never a claimed zero query count.
`sql_observed_response_count` and `sql_unknown_request_count` disclose coverage;
SQL rates/phase timings divide by observed responses and hit ratios exclude lost
responses. The report displays error rates and unknown SQL counts separately.
This policy corrects the earlier all-or-nothing measurement limitation and does
not weaken injected-failure or resource-cleanup checks.

Version 2.3 adds a benchmark-only HTTPcore AnyIO pool-readability guard on Windows.
Only `WinError 10038` (an already invalid socket during an idle descriptor check)
is treated as expired, matching HTTPcore's existing missing/negative descriptor
behavior. Other OS errors propagate. No sent request is replayed; connection
pool settings, timeouts, workload and production libraries remain unchanged.
The number of such expired-socket checks is recorded in runtime metadata.
The retained complete cold capture used version 2.2 (and its exact source is
retained); matched warm/current-control runs use 2.3. These observer differences
are disclosed rather than replacing or relabeling the captured data.

Verify real failure cleanup and hostile ambient configuration in a separate
disposable service project:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/verify-menu-benchmark-cleanup.py
```

This expects exit 1 from each injected seed/measurement/HTTP-request failure,
asserts zero result artifacts/allocated databases/new owned Redis containers,
checks that the connection-template database was never migrated, and finally
removes only its own Compose project. Logs contain safe categories/status counts.

Retain the baseline and successful comparison JSON under
`docs/milestone7/benchmarks/`, then regenerate the tracked table (repeat
`--candidate` for cold/outage/restart):

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/report-menu-read-comparison.py --baseline docs/milestone7/benchmarks/baseline.json --candidate docs/milestone7/benchmarks/warm.json --candidate docs/milestone7/benchmarks/cold.json --candidate docs/milestone7/benchmarks/outage.json --candidate docs/milestone7/benchmarks/restart.json --output docs/milestone7/performance-milestone7.md
```

The report rejects seed/mix/sample/repetition drift, missing full warm/cold cells,
duplicate cells and inconsistent error/observation/query/hit accounting.
Summary percentiles are the median of three repetition percentiles, not pooled
request samples. Individual repetitions and JSON hashes remain available.
Historical versus current instrumentation/runtime/revision differences are
disclosed; do not attribute every latency change solely to caching.

For a new contemporaneous uncached control, use `--cache-state disabled`; this
disables only catalog lookup in the dedicated benchmark process while preserving
fresh authorization, live stock, normal sessions and writes. It does not replace
the original baseline requested for issue #27.

The supplemental control runs the complete original 48-cell workload with
1,000 requests, 50 warm-ups and three repetitions at concurrency 1/10/25/50.
It helps interpret observer/application changes between the old
baseline and current runs; serial runs are not randomized paired measurements.

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-menu-reads.py --isolated --cache-state disabled --output-dir artifacts/benchmarks/issue27-control
backend/.venv-m6-dev/Scripts/python.exe scripts/report-menu-read-comparison.py --baseline docs/milestone7/benchmarks/current-control.json --candidate docs/milestone7/benchmarks/warm.json --shared-cells --output docs/milestone7/performance-milestone7-control.md
```

`--shared-cells` selects rows in memory and hashes the unmodified complete source
artifacts. It never edits the retained warm JSON or substitutes the current
control for the original historical capture.

### Optional dashboard experiment

The separate experiment reuses the same authenticated harness and adds 700
completed paid historical orders over seven days, two immutable item snapshots
per order (1,400 rows). It does not alter the original catalog benchmark dataset.
It compares the live dashboard with a **benchmark-only** Redis prototype caching
the four aggregate query results after fresh authorization. Production dashboard
caching remains absent. It has a ten-second source-age bound but no order-write
invalidation and therefore is not an approved production cache design.

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-dashboard-cache.py --isolated --output-dir artifacts/benchmarks/issue27-dashboard-live
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-dashboard-cache.py --isolated --prototype --output-dir artifacts/benchmarks/issue27-dashboard-prototype
backend/.venv-m6-dev/Scripts/python.exe scripts/report-menu-read-comparison.py --baseline docs/milestone7/benchmarks/dashboard-live.json --candidate docs/milestone7/benchmarks/dashboard-prototype.json --output docs/milestone7/performance-milestone7-dashboard.md
```

Keep the experimental script SHA256 and limitations with its measurements. Assess
latency/query savings alongside consistency across aggregates, completed-order
edits/deletions, report dates/timezones, tenant scoping, shared-process clock/TTL
behavior and acceptable freshness. An implement/defer recommendation belongs in
the issue #27 evidence; shipping a cache requires reviewed follow-up scope.

Check the freshness tradeoff separately through a real permitted legacy-order
delete, without mixing writes into the latency experiment:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/verify-dashboard-cache-freshness.py
```

The owned dataset has no processed stock/replay history. Live reads must reflect
the committed deletion immediately; the prototype retains its old aggregate
until its ten-second expiry. The probe also verifies unchanged inventory and a
transactional deletion audit, then publishes `dashboard-freshness.json` only
after all owned services/databases are removed. This is evidence for deferral,
not permission to accept stale production dashboards.
Hard deletion is Owner-only: the probe verifies Manager 403, performs the delete
through a separate Owner cookie session (204), and reads aggregates as Manager.
