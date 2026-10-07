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

The corrected default full capture is pending at the time of this intermediate
update; this paragraph will be replaced with the completed run evidence.
