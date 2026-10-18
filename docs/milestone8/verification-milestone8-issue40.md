# Milestone 8 issue #40 verification

Reviewed: 2026-10-17 (Asia/Bangkok).
Sources: [issue #40](https://github.com/ShinningF1eld/RestaurantOS/issues/40),
[approved design revision 1](milestone-8-design.md), T10 in
[the task plan](milestone-8-task.md), dependency slices #36–#39 and their dated
verification. The design governs where the roadmap's initial event list or
historical implementation descriptions differ.

Comparison base: `b8f022d4b4eb2343b729651d1b0c6a3fbda9e63a`, initially clean tree.
Scope: uncommitted T10 regression/gate/cleanup changes and documentation.
This is the implementing agent's review, not independent review or remote CI.
Environment: Windows, Python 3.12.13 (`backend/.venv-m6-dev`), Node 24.14.1,
locked dependencies and disposable PostgreSQL 16 / Redis 7 / production Next.js
/ Chromium. No application database migration, cutover, commit, push or publication.

## Change responsibilities

- `test_event_producer_process.py` extends the actual authenticated API death
  test beyond pending fan-out: direct recovery, killed relay after XADD, and
  deleted stream all finish through the production worker. Every subscribed
  delivery has one receipt; actual alert, low-stock stub and correlated order
  diagnostic outcomes are checked.
- `test_event_execution.py` / `support/event_worker_process.py` add a real-clock
  event-specific failing sink. Restart during exponential backoff preserves
  eight attempts and due spacing; real analytics succeeds independently once.
  After explicit operator replay, the production sink succeeds and old attempt
  and replay facts remain. This supplements existing exact-clock boundary tests.
  Test wiring is exclusively in `tests/support`; production exposes no test flag.
- `test_event_worker.py` extends physical nonpersistent Redis restart recovery
  through the production sink and verifies one receipt and diagnostic effect.
- `auth/test_redis_admission.py` corrects a pre-existing accounting-test window
  assumption discovered by full validation. It selects a known open fixed window
  from real Redis server time and verifies the recorded expiry, retaining real
  Lua, exact ten-charge/eleventh-throttled assertions, current quotas and auth
  deadlines. The separate real expiry/boundary test is unchanged.
- `test_validation_cleanup.py` starts separate owned Compose services, migrates
  an allocated `_test` database and starts a real production worker. An injected
  exception triggers process wait, database drop and Compose teardown. Container,
  network and volume queries verify that project's resources are gone.
- `test_support/processes.py` and the browser runner attempt cleanup for every
  owned child even when an earlier child's cleanup fails; terminate/kill waits
  are bounded. Previously a worker cleanup exception could bypass API cleanup.
- `validate.py` includes the modified harness in `backend-static` and requires
  the browser failure-cleanup probe after normal Chromium workflows. It requires
  the expected assertion failure/exit code and checks container/source-copy
  cleanup plus a fresh attestation after all cleanup contexts succeed;
  stale/missing/unrelated JUnit failures or cleanup errors cannot satisfy it. Safe expected
  failure artifacts have their own directory and existing CI retention applies.
- `unit/test_validation_policy.py` checks the parsed real CI configuration,
  unchanged aggregate, ten gates/events, absence of conditional/ignored gate
  failures, broad worker-suite discovery, unit environment isolation and cleanup
  error/timeout/probe rejection paths. No workflow/ruleset modification.

No production business, schema, HTTP contract, frontend UI, dependency lock,
runtime image, migration graph or worker retry-policy change. Existing slice
regressions are reused; the [regression map](../testing/milestone8.md) maps R1–R14
to executable coverage. The five-second healthy processing measurement remains
#41, and UI cadence does not establish processing freshness.

## Acceptance review

Final local implementation review passes criteria 1–5 with fresh execution.
No remaining actionable finding was identified in the change set. Criterion 6
has a passing full local run and untested final PR CI; it is not fully accepted.
No issue or Milestone 8 completion is claimed.

| Issue criterion | Result | Evidence |
|---|---|---|
| 1. Actual API/worker crash, publication/ACK ambiguity, pending reclaim and Redis loss; unique outcomes | Passed (execution/inspection) | Final integration passes cross-feature API death matrix, existing real worker/actual-consumer crash tests and extended physical Redis restart case. |
| 2. Poison isolation, eight durable retries/restart, outages, unsupported version, replay/fencing and lock-proven overlap | Passed (execution/inspection) | Final integration passes real-clock process restart/replay, controlled-clock, actual PostgreSQL disconnect, Redis outage, unsupported-contract and barrier/lock suites. |
| 3. Producer atomicity/idempotency, analytics, episodes/stub timing, baselines and scoped/UI behavior | Passed (execution/inspection) | Final backend/component/29 Chromium cases pass; suite mapping in `docs/testing/milestone8.md`. |
| 4. Required discovery, guarded/isolated resources and failure cleanup; auth traces disabled | Passed (execution/inspection) | Final policy tests, nested real worker/service failure and required intended-failure browser probe pass. Guards, source-copy ownership and trace-off setting retained. |
| 5. Clean/seeded migrations, drift/preservation/downgrade guards; conditional image changes | Passed (execution/inspection) | Final migration gate passes M8 retained/replay/stock/history guards and backup/restore CLI rehearsal; `alembic check` passes. Image unchanged; final image gate verifies startup without migration. |
| 6. Full locked-install local command and final complete PR CI | Passed locally; Untested final PR CI | Final full command passes all ten gates on Python 3.12/Node 24. Final PR CI cannot run for this uncommitted/unpushed change. Criterion remains open. |

## Commands and outcomes

```powershell
./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-static --gate backend-unit --no-install
git diff --check
```

Final complete execution returned 0 with `PASS: full validation`. Evidence:
`test-results/issue40-final-complete-validation.log`. This run collected the
final implementation, including the auth accounting correction and mandatory
browser cleanup probe; no implementation edits followed it.

| Gate | Final outcome |
|---|---|
| baseline | Passed: committed hash-checked Python / npm installs, Compose config, pip integrity and candidate-file secret scan. |
| backend-static | Passed: Ruff lint/format, mypy (163 application sources), modified harness lint/format. |
| frontend-static | Passed: ESLint, Prettier, generated Next route types and TypeScript. |
| backend-unit | Passed: 294 cases, no services. |
| backend-integration | Passed: 333 cases, followed by `alembic check` with no new upgrade operations. |
| frontend-tests | Passed: 10 client and 19 component cases. |
| frontend-build | Passed: isolated production source copy. |
| migrations | Passed: clean/seeded/backup-restore CLI rehearsal, legacy preservation, all retained-history guards and model drift. Unique head remains `c3d8e1f52a74`. |
| browser | Passed: 29 real Chromium/API/worker workflows (4.5 minutes); intended assertion failure returned 1 and required probe accepted its report, fresh cleanup attestation and absence of leaked resources. Auth traces off. |
| image | Passed: Python 3.12 locked/nonroot runtime, content inspection, production liveness/database connectivity, startup without schema changes and cleanup. |
| Final diff / owned resources | `git diff --check` passed. Test projects, workers and temporary copies were removed. HEAD remains the comparison base; all task changes are uncommitted. |

Existing Starlette TestClient and naive-UTC SQLAlchemy deprecation warnings remain.
Only final remote PR CI and #41's measured freshness/operational evidence are
omitted from milestone acceptance; no local shared gate was omitted in this run.

Intermediate execution (before the final full run): the first full locked-install
command passed all ten gates with 288 unit cases, 332 integration cases plus
`alembic check`, 10 client / 19 component cases, 29 Chromium workflows,
clean/seeded/backup-restore migration rehearsals and image startup without schema
changes. That process had loaded the earlier gate code and had collected before
the final poison-process addition; it does not establish final-source acceptance.
The final full command is rerun after completing implementation and review.

The real-clock poison restart/replay and actual nested cleanup cases separately
passed together (2 tests, 142.36 seconds), within the shared disposable-service
and guarded-database helpers after `alembic upgrade head`:

```powershell
# Inside the owned services / disposable_database environment, cwd backend:
python -m pytest tests/integration/test_event_execution.py::test_real_poison_worker_restart_preserves_eight_attempts_and_other_consumer tests/integration/test_validation_cleanup.py -q
```

Intermediate selected host-access static/unit checks passed Ruff, mypy and 294
unit cases after adding the cleanup-attestation rejection regression. The final
full run also collects the subsequent CI matrix-exclusion/aggregate guards.

The final browser cleanup probe passed independently through
`runpy.run_path('scripts/validate.py')`, `services(False)` and
`browser_cleanup_probe(env)`. Its child returned the intended exit 1, JUnit held
exactly `diagnostic failure`, the fresh attestation recorded completed cleanup,
and no new owned Redis container/source copy remained. The wrapper returned 0
and removed its disposable outer Compose services. Safe evidence is in
`test-results/issue40-browser-cleanup-probe.log` and `test-results/browser-cleanup/`.

The first final-source full attempt failed: 332 integration cases passed and
`test_refresh_known_family_accounting_and_storage_error_release` failed with
`2 == 10` at the Redis charge-count assertion; model-drift and subsequent gates
did not run in that attempt. All disposable resources were removed. No auth
transport/dependency exception was reported. Inspection showed the test counted
across real fixed minute windows, whose finalized records legitimately expire
at the boundary; the observed two surviving charges are consistent with crossing
that boundary after eight rotations. The earlier full run passed that unchanged
test. The correction establishes the single-window precondition explicitly
without changing production Lua, quotas, deadlines or boundary-expiry behavior.
This is a failed run and a test-only correction, not a green rerun substituted
for the original failure record. Failure evidence remains in
`test-results/issue40-final-full-validation.log`; another complete locked-install
run follows focused accounting/boundary repetitions.
The failed log retains the traceback/count evidence with the static fixture
password redacted; no cookies, generated credentials or auth traces are retained.

Focused correction verification: ten separate invocations of the corrected
accounting case and unchanged `test_real_redis_expired_leases_and_fixed_windows`
passed (20 test executions) in a guarded disposable database after migrating to
head. Each invocation uses fresh fixtures; the owned service project and database
were removed. See `test-results/issue40-auth-accounting-repetitions.log`.

Implementation review identified and corrected an intermediate probe gap: an
expected JUnit failure with exit 1 alone could mask a subsequent teardown error.
The final probe requires the runner's fresh post-cleanup attestation as well.
A policy regression rejects an otherwise valid expected-failure report when
cleanup did not attest success. This is a corrected implementation finding,
not a remaining defect.

An early selected static/unit run without host access stalled after collecting
293 unit cases in the known Windows socket-guard/sandbox interaction and was
interrupted. It is not counted as a pass. The host-access full run's earlier
source passed 288 unit tests; that historical/intermediate count does not prove
the subsequently added policy/probe tests or final source.

Safe local logs: `test-results/issue40-*.log`; ordinary browser artifacts:
`test-results/browser/`; expected-failure artifacts: `test-results/browser-cleanup/`.
No authentication traces are enabled. Dated outcomes here remain the retained
record if ignored logs are replaced by future runs.

Locked `npm ci` reported six high-severity dependency advisories in the existing
lock. This task does not upgrade dependencies or assess those advisories; the
shared gates do not currently enforce `npm audit`. This is a disclosed baseline
limitation, not an introduced dependency change or a claim of vulnerability-free
acceptance.

## Limits

Final remote PR CI is untested because the user requested no commit. No GitHub
issue checkbox/state/comment was changed. Full Milestone 8 acceptance remains
open for complete CI and #41 freshness/operational evidence. Local validation
never targets the application database or deletes the developer volume.
