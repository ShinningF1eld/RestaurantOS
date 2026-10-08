# Milestone 7 Issue #20 verification

Date: 2026-10-07 (Asia/Bangkok). Reviewed commit:
`7559b331d175748a80c58d4932c4ebe533cd7da7`, branch `milestone7`.
Comparison: its parent, `6da9476903c6483544c97f6925f34af86b8908d7`.
Working tree was clean at review start. Sources: root engineering instructions,
README/current-state, approved design revision 11, T2, live
[Issue #20](https://github.com/ShinningF1eld/RestaurantOS/issues/20), testing
instructions, benchmark implementation and existing disposable database helper.
Issue #20 was closed as completed when inspected. This review changes no issue
state or implementation.

Current follow-up outcome: all three findings are fixed. The corrected full
baseline and final configuration-loader validation are recorded below; the
original review is retained as history.

## Verdict

This section records the original review of `7559b33`. The fixes and new
verification are recorded in the follow-up section below.

The implementation demonstrates a working uncached authenticated HTTP benchmark,
but does not fully satisfy the reproducibility and failure requirements. The
mixed-write workload differs from its recorded definition; inherited application
settings can change the measured configuration; measured request failures do not
make the runner fail. Correct these before treating the checklist as fully passed.

## Findings

1. **P1: Recorded mixed-write workload is incorrect.**
   `scripts/benchmark-menu-reads.py:251` and `:262` each select one write in every
   five requests. Together they produce 40% writes (20% item updates, 20% menu
   updates) and 60% reads. Metadata at `:448` and the procedure claim 20% writes
   (10% each) and 80% reads. Executing the request planner for measured indices
   50–1049 produced 400 PUTs and 600 GETs. The existing full-run artifact contains
   the same incorrect description. This mislabels the workload used for later
   comparisons. Choose the intended ratio, align planner/docs/metadata, and
   recapture or explicitly correct the historical evidence.

2. **P2: Effective configuration can differ from recorded configuration.**
   `scripts/benchmark-menu-reads.py:489` updates the existing process environment;
   it does not remove the variables filtered out of the separate migration
   environment. `backend/app/core/config.py:24` also loads `backend/.env`.
   Unspecified settings can therefore come from the caller or that file, despite
   the procedure's claim that no `.env` file is read. A configuration-only probe
   using the helper-generated environment and inherited `AUTH_ACCESS_SECONDS=7`
   and `DATABASE_ECHO=true` produced an effective seven-second lifetime and SQL
   echo enabled. Metadata nevertheless hard-codes 600 seconds and does not record
   the effective echo setting. Short expiry can invalidate measured requests;
   SQL logging can alter latency. Explicitly isolate benchmark settings from local
   configuration and record the effective settings. The generated database URL
   still overrides the developer URL, so this finding does not demonstrate any
   developer database mutation.

3. **P2: Measured HTTP failures can produce a successful artifact and exit.**
   `measure_scenario` records non-2xx responses and transport errors but returns
   normally. A support-code probe with five HTTP 500 responses returned five
   errors without raising. The result is accepted by `run_benchmark`, and
   `main` writes its artifact at `:648` and returns zero at `:658` without checking
   the measured error counts. With warm-up disabled, even a wholly failed workload
   can follow this path. Define a success/error policy and make failed runs
   nonzero with an explicit failed-result status or no successful result artifact.

## Acceptance coverage

| Requirement | Status | Evidence |
|---|---|---|
| Issue criterion 1: deterministic dataset, memberships, stock, mixes, concurrency and cache states | Failed | Seed and workload inspection; real smoke succeeds, but mixed-write ratio is incorrectly documented. |
| Issue criterion 2: metrics, method, warm-ups, repetitions and metadata | Failed | Latency, request/error/query metrics execute correctly; effective runtime configuration is not reliably reproduced by metadata. |
| Issue criterion 3: guarded existing disposable lifecycle and safe artifacts | Passed for exercised paths | Unsafe URL guards reject; real success, seed-failure and measurement-failure runs remove allocated databases; helper scopes allocation/drop to generated names; artifact metadata contains no credentials/auth identifiers by inspection. |
| Issue criterion 4: reusable mixes/schema and dashboard evaluation evidence | Failed | Schema and dashboard evidence requirements exist, but recorded mix does not match execution. |
| User requirement: real HTTP/auth/authorization/catalog path | Passed | Uvicorn loopback TCP server, normal Manager login/cookies and application dependencies; both endpoints return 200 in smoke. |
| User requirement: benchmark failures return nonzero | Failed | Injected exceptions return 1, but measured HTTP failures are accepted as ordinary results. |
| User requirement: success/failure resource cleanup | Passed for exercised paths | Zero allocated benchmark databases after each of three runs; only one success JSON; test Compose containers/network removed. |
| Full default benchmark rerun on reviewed commit | Untested in this review | Ran a short smoke only; inspected the existing full-run evidence instead. |
| Abrupt process termination, migration failure and artifact-write failure | Untested dynamically | Cleanup/atomic-write implementation inspected; these failure points were not injected. |

The T2 checklist has the same mix/reproducibility gaps. No Redis caching, cache
behavior, schema, API contract or authentication bypass was added by the commit.

## Execution evidence

- `backend/.venv-m6-dev/Scripts/python.exe -m ruff check scripts/benchmark-menu-reads.py`
  passed.
- `backend/.venv-m6-dev/Scripts/python.exe -m ruff format --check scripts/benchmark-menu-reads.py`
  passed.
- `backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-static --no-install`
  passed: Ruff, format check (152 files), mypy (119 sources). This is partial
  validation, not full milestone acceptance.
- Python AST syntax parsing and nearest-rank percentile probe passed: for values
  1–1000, P50/P95/P99 are 500/950/990.
- Existing helper rejected absent TEST_DATABASE_URL, an application database name
  without `_test`, and a remote host outside its allowlist.
- Used `scripts/validate.py`'s existing `services(False)` context for a unique
  disposable Compose project and the benchmark's existing database helper.
  Executed the benchmark with `--requests 20 --warmup 2 --repetitions 1
  --concurrency 1,2 --output-dir artifacts/benchmarks/review-issue20`.
  Real migrations, seed, login and all four scenarios passed: eight cells,
  160 measured requests, zero errors, nonzero query counts. This establishes
  harness behavior; twenty requests per cell are insufficient for a new
  meaningful P99 baseline.
- Repeated that command with `--inject-failure-after seed` and with
  `--inject-failure-after measurement`: each returned 1 and left no allocated
  benchmark database or additional JSON artifact. Successful API shutdown is
  required by the runner before returning; the successful smoke returned 0.
- Smoke artifact:
  `artifacts/benchmarks/review-issue20/menu-read-baseline-20261007T123517Z-5e42aac5.json`.
  Parsed and verified eight result cells, zero errors and positive query totals.
- Existing full artifact:
  `artifacts/benchmarks/menu-read-baseline-20261007T120114Z-75f7ad6d.json`.
  Parsed 48 cells / 48,000 measured requests / zero errors. Its script SHA-256
  matches the reviewed script. It records the parent commit with a dirty-worktree
  flag; the matching script hash supports attribution of the harness, but is not
  a complete fingerprint of all application code/configuration.

No full unit/integration/browser/image/migration acceptance suite was rerun:
the focused live smoke exercises the benchmark's migrated database and endpoint
paths. Generated review artifacts are ignored. No fixes, commits, pushes or
GitHub updates were performed.

## Follow-up fixes and verification

Version 1.1.0 fixes all three findings: mixed writes use a ten-request cycle
(one item update, one menu update, eight reads); every application settings field
is initialized explicitly with dotenv disabled; migrations, seed and API resolve
the same settings instance; effective nonsecret settings are included in metadata.
Any measured non-2xx or transport failure now rejects the entire capture, exits
nonzero and publishes no result artifact.

Focused regressions: `backend/.venv-m6-dev/Scripts/python.exe -m pytest
tests/unit/test_menu_read_benchmark.py -q --basetemp
../artifacts/benchmarks/pytest-issue20` from `backend/`: **11 passed**. These cover
mix ratios at four warm-up offsets, conflicting ambient and dotenv settings,
HTTP/transport/missing-instrumentation failures with zero warm-up, excluded
warm-up SQL, nonzero runner exit/cleanup, and atomic artifact-write failure.
The repository backend-static gate and explicit script lint/format checks pass.

Real PostgreSQL failure runs used existing disposable Compose infrastructure and
the existing database helper. `--inject-failure-after seed`, `measurement`, and
`request`, each with `--requests 20 --warmup 0 --repetitions 1 --concurrency 1,2`,
returned 1, wrote no result JSON, and left zero allocated benchmark databases.
All runs inherited conflicting `AUTH_ACCESS_SECONDS=7`, `DATABASE_ECHO=true`,
and `ENVIRONMENT=production` deliberately to exercise configuration isolation.

The corrected default capture completed all **48 cells / 48,000 measured
requests with zero errors**, using 1,000 measured requests and 50 excluded warm-up
requests per cell, concurrency 1/10/25/50 and three repetitions. Artifact:
`artifacts/benchmarks/corrected/menu-read-baseline-20261007T130416Z-c6ac7674.json`.
The JSON records clean implementation revision
`aa01cde845ba5b780f6875abdca274fc452ad70c`, script version 1.1.0, and a script
SHA-256 matching that revision. It was parsed and verified to contain all cells,
request totals, zero errors, positive actual SQL counts, required runtime metadata,
and the expected effective settings. Python 3.12.13 / PostgreSQL 16.15.

Average SQL counts per measured request: menu-list 6, menu-items 7, mixed-read
6.8, mixed-write 7.500916666666667. The small first mixed-write difference from
7.5 reflects actual first-time mutations; these counts were measured, not assumed.
Per-cell P50/P95/P99 and status counts are in the artifact. The allocated database
count after the successful run was zero, and its Compose containers/network were
removed. The original version 1.0.0 artifact is superseded and must not be used
for the future cached comparison.

Final setup hardening in version 1.1.1 restricts Pydantic settings sources to
explicit inputs. Supplying every field alone still allowed Pydantic to parse an
invalid inherited JSON value before resolving input precedence; the final loader
ignores those sources entirely while retaining all application validators. The
settings regression now includes invalid `AUTH_TRUSTED_ORIGINS` and
`AUTH_TRUSTED_PROXY_IPS`, and all 11 focused tests pass again. A final real smoke
uses these invalid inputs plus the scalar conflicts, exercises both successful
HTTP reads/writes and an injected failed request, verifies zero leftover
databases, and compares effective settings exactly with the full capture. This
change affects setup only; measured requests, workload and metric calculation
are unchanged. The clean version 1.1.0 full capture remains valid comparison
evidence, with its exact implementation revision and script hash preserved.

Broader validation command:
`backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline
--gate backend-unit --gate backend-integration --no-install`.
Passed baseline (Compose config, dependency integrity, candidate secret scan),
**144 unit tests** including the 11 new regressions, **183 real PostgreSQL
integration/characterization tests**, clean database upgrades, Alembic drift
check and Redis infrastructure namespace cleanup. The test Compose project was
removed. Existing dependency/datetime deprecation warnings remain. Backend-static
also passed (Ruff/format/mypy); this is partial issue validation, not whole
Milestone 7 acceptance. The final source loader is additionally checked by the
focused unit rerun and real smoke described above.

All four Issue #20/T2 acceptance criteria now pass for the corrected capture:
dataset/mixes are accurately defined, metrics and effective metadata are recorded,
owned disposable resource safety is exercised on success and failure, and the
same versioned workload/schema plus dashboard evaluation requirements remain
available. Abrupt termination and full Milestone 7 acceptance remain outside
this focused verification; this does not claim that the whole milestone passes.


## Recorded latency baseline

These tracked tables preserve all 48 result cells from the corrected JSON capture
at `2026-10-07T13:04:16.107257+00:00`, implementation `aa01cde`, script version 1.1.0.
Latencies are client-observed milliseconds, rounded to two decimal places;
P50/P95/P99 use nearest-rank within each cell. Each row contains 1,000 measured
requests after 50 excluded warm-ups. Every row has 1,000 successful requests,
zero errors (0% error rate), and cache-hit ratio N/A. These are measured local
results, not deployment performance targets. The full-precision JSON remains
the machine-readable comparison source.

### Repetition 1

| Scenario | Concurrency | P50 ms | P95 ms | P99 ms | PostgreSQL statements |
|---|---:|---:|---:|---:|---:|
| menu-list | 1 | 15.60 | 19.42 | 22.57 | 6000 |
| menu-list | 10 | 150.72 | 304.02 | 367.66 | 6000 |
| menu-list | 25 | 421.57 | 1350.36 | 1945.53 | 6000 |
| menu-list | 50 | 722.15 | 3008.78 | 4392.76 | 6000 |
| menu-items | 1 | 18.61 | 22.83 | 26.59 | 7000 |
| menu-items | 10 | 166.02 | 305.22 | 350.56 | 7000 |
| menu-items | 25 | 438.65 | 1441.21 | 2330.58 | 7000 |
| menu-items | 50 | 796.22 | 3243.19 | 5339.96 | 7000 |
| mixed-read | 1 | 18.66 | 23.94 | 26.95 | 6800 |
| mixed-read | 10 | 162.66 | 303.37 | 415.13 | 6800 |
| mixed-read | 25 | 417.18 | 1337.41 | 1959.55 | 6800 |
| mixed-read | 50 | 792.05 | 3214.82 | 4815.96 | 6800 |
| mixed-write | 1 | 18.73 | 25.43 | 28.93 | 7511 |
| mixed-write | 10 | 170.17 | 384.98 | 534.59 | 7500 |
| mixed-write | 25 | 440.80 | 1450.75 | 2099.95 | 7500 |
| mixed-write | 50 | 829.50 | 3383.16 | 5623.13 | 7500 |

### Repetition 2

| Scenario | Concurrency | P50 ms | P95 ms | P99 ms | PostgreSQL statements |
|---|---:|---:|---:|---:|---:|
| menu-list | 1 | 15.68 | 19.13 | 22.77 | 6000 |
| menu-list | 10 | 144.85 | 370.47 | 450.19 | 6000 |
| menu-list | 25 | 322.47 | 990.50 | 1593.20 | 6000 |
| menu-list | 50 | 616.11 | 2378.71 | 3817.58 | 6000 |
| menu-items | 1 | 16.36 | 20.63 | 24.99 | 7000 |
| menu-items | 10 | 157.73 | 335.87 | 486.73 | 7000 |
| menu-items | 25 | 361.41 | 1250.85 | 1692.34 | 7000 |
| menu-items | 50 | 675.79 | 2936.87 | 4483.44 | 7000 |
| mixed-read | 1 | 18.35 | 29.33 | 36.26 | 6800 |
| mixed-read | 10 | 146.89 | 356.38 | 419.56 | 6800 |
| mixed-read | 25 | 379.20 | 1257.52 | 1898.50 | 6800 |
| mixed-read | 50 | 719.37 | 2801.37 | 4516.45 | 6800 |
| mixed-write | 1 | 17.24 | 22.66 | 25.60 | 7500 |
| mixed-write | 10 | 153.24 | 350.97 | 479.20 | 7500 |
| mixed-write | 25 | 394.04 | 1235.83 | 1869.28 | 7500 |
| mixed-write | 50 | 730.72 | 3224.97 | 4676.63 | 7500 |

### Repetition 3

| Scenario | Concurrency | P50 ms | P95 ms | P99 ms | PostgreSQL statements |
|---|---:|---:|---:|---:|---:|
| menu-list | 1 | 14.42 | 17.41 | 21.02 | 6000 |
| menu-list | 10 | 131.11 | 352.59 | 396.90 | 6000 |
| menu-list | 25 | 342.64 | 1153.58 | 1565.79 | 6000 |
| menu-list | 50 | 678.85 | 2805.44 | 4546.14 | 6000 |
| menu-items | 1 | 17.50 | 21.71 | 26.00 | 7000 |
| menu-items | 10 | 169.10 | 359.41 | 405.91 | 7000 |
| menu-items | 25 | 414.44 | 1387.29 | 2040.94 | 7000 |
| menu-items | 50 | 818.55 | 3307.10 | 5028.69 | 7000 |
| mixed-read | 1 | 19.06 | 23.03 | 26.19 | 6800 |
| mixed-read | 10 | 126.86 | 329.75 | 406.33 | 6800 |
| mixed-read | 25 | 421.55 | 1413.98 | 2102.32 | 6800 |
| mixed-read | 50 | 683.22 | 2873.78 | 4229.31 | 6800 |
| mixed-write | 1 | 20.54 | 31.28 | 45.38 | 7500 |
| mixed-write | 10 | 173.63 | 408.54 | 570.51 | 7500 |
| mixed-write | 25 | 439.94 | 1522.77 | 2280.15 | 7500 |
| mixed-write | 50 | 825.54 | 3479.92 | 5074.40 | 7500 |

### Comparing the cached version

Match dataset, hardware/runtime, effective settings, endpoint mix, concurrency,
warm-up count, measured count and repetitions. Compare warm-cache results against
the matching scenario/concurrency/repetition rows above; report cold fills as a
separate workload. Repeat the same mixed-write cycle to measure reads while
catalog changes occur. Capture actual cache hits and preserve normal authorization
and live stock reads.

For each matched cell, report baseline and cached P50/P95/P99, latency change
`100 * (cached_latency / baseline_latency - 1)`, PostgreSQL statements/queries per
request, errors and cache-hit ratio. Divide statement totals by 1,000 for the
queries/request values in these tables. Keep all three repetitions visible;
do not average their percentiles and label that value a pooled percentile. Save
the cached JSON next to the baseline and add its measured tables to tracked
documentation. Latency and query reduction are both comparison outcomes.
