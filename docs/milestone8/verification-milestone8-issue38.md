# Milestone 8 issue #38 verification

Reviewed: 2026-10-15 (Asia/Bangkok).
Sources: [issue #38](https://github.com/ShinningF1eld/RestaurantOS/issues/38),
[T8 task criteria](milestone-8-task.md), authoritative approved revision 1 of
[the M8 design](milestone-8-design.md), ADRs 0001/0002, event/projection contracts
and migration/worker runbooks. Dependencies #36/#37 are implemented at the base.
Comparison base: `ab8beeece1815131c4cd427deb3ffb9cd85fd792`, initially clean tree.
Reviewed changes: issue #38 implementation and documentation, before its local
commit. Review used the review-verify workflow; this is an implementation-agent
review, not an independent agent or remote CI review.
Environment: Windows, Python 3.12.13, PostgreSQL 16/Redis 7 in isolated Compose
projects; committed dependencies already installed in `backend/.venv-m6-dev`.

## Result

All six issue criteria passed inspection and disposable execution. No actionable
implementation findings remain. Application migration/initialization was not
performed. Full Milestone 8 acceptance remains open for T9–T11 and all shared gates.

## What changed and why

- `events/maintenance.py` owns a per-scope transaction and uses inventory's public
  lock/state/baseline APIs, analytics' transaction-bound rebuild and alerts'
  public rebuild. Analytics, suppressed legacy episodes, alert projection and
  initialization provenance commit together. An interruption rolls all of them
  back. Concurrent initialization serializes on the shared restaurant lock.
- `events/repo/maintenance.py` owns scoped marker/provenance persistence and
  event-history counts. A partial unique index permits exactly one initialization
  marker per restaurant while retaining every committed analytics rebuild.
  Provenance contains operation UUID, scope, database `session_user`, reason and
  database observation time. A committed initialization rerun returns its existing
  UUID/time without reseeding or recreating resolved episodes.
- `analytics/service.py` exposes `rebuild_analytics_projection(session, ...)` so
  T8 can include reconstruction in its transaction. The existing service rebuild
  delegates to the same algorithm; revision watermarks, deletion tombstones,
  decimal totals and live-SQL dashboard behavior are preserved.
- `events/cli.py` adds `initialize` and `analytics-rebuild`. Both require explicit
  scope, reason and `--maintenance-confirmed`. Rebuild requires prior initialization.
  Safe JSON reports operation identity/provenance and retained counts, omitting
  payloads, reason text and raw exceptions. No HTTP endpoint or frontend changed.
- Additive migration `c3d8e1f52a74` follows `b2c7d9a41e63`, creates only the
  maintenance table/index/constraints, and refuses downgrade with retained
  provenance. Shared metadata and Alembic registration include the model.
- `scripts/verify-migrations.py` rehearses a custom-format backup/restore and
  legacy cutover CLI sequence on a second disposable database. Integration tests
  exercise legacy/new facts, recovery/rerun, retained histories and actual worker
  startup followed by resumed stock writes. Contracts, testing maps, README,
  current-state, roadmap and the executable maintenance runbook explain operation.

Only active-low ingredients with no producer episode get a baseline. Existing
producer episodes retain their truthful source and notification eligibility.
Baselines use current observation time and immutable opening snapshots, emit no
historical events, and remain suppressed until resolution and a new low episode.
This implements the approved design without inventing earlier lifecycle history.

## Criteria and coverage

| Issue criterion | Status | Evidence |
|---|---|---|
| 1. Explicit quiesce/stop, actual revision/backup, migrate, seed/baseline/suppress, start/resume sequence | Passed | Executable `event-maintenance.md`; migration gate dumps seeded legacy data, restores another database, checks revision/business snapshots, explicitly migrates and exercises production CLI. Final real-worker regression starts `app.worker` after initialization, drains queued work and resumes stock writes. |
| 2. Existing completed orders, revision fences, no historical transitions, retained pending events/receipts | Passed | Initializer uses current-order and retained deletion watermarks. Tests compare complete outbox/delivery rows before/after initialization, deliver queued completion/deletion/inactive older events and reconcile; retained successful receipts survive init/rebuild. Legacy CLI rehearsal emits zero events/receipts. |
| 3. Truthful observed baseline facts and scoped repeatable provenance | Passed | Baseline time is bounded by test observation times; immutable name/unit/quantity/threshold/source/suppression checked. Other branch stays uninitialized; foreign organization scope fails. Concurrent calls produce one episode/marker and identical operation UUIDs, with PostgreSQL-observed lock waiting. |
| 4. Suppression until recovery/new episode, reruns with stock/threshold/archive/history | Passed | Parametrized stock recovery, threshold reduction and archive paths; still-low edits preserve baseline snapshots; resolved rerun creates nothing; new low episode creates a normal stub. Real worker catches up old state without baseline notification, then records exactly one new episode stub after resumed writes. T7's existing suppressed-event handler regression also passes in full integration. |
| 5. Reconstruction preserves alert/event/attempt/replay/receipt/stub history; reconcile/counts/retention limits | Passed | Test snapshots retained tables containing real successful receipts, attempts, replay provenance, low-stock stub and menu diagnostics; corrupts daily sales; rebuild restores SQL equality with all retained rows unchanged. Queued replay and receipt redelivery remain harmless. Safe scoped counts and no-pruning/storage limitations are documented. |
| 6. Executable trusted CLI, safe output, preconditions, interruption/rerun and backup, disposable validation | Passed | Production CLI exercised by migration gate; reason/attestation/scope validation inspected. Injected interruption after analytic/baseline/alert effects rolls all tables and marker back, then rerun succeeds. Backup restored and compared. Validation sets both URLs through guarded database environments and removes owned resources only. No application operation or developer-volume deletion. |

## Executed checks

From repository root, using the existing locked Python 3.12 environment:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-unit --no-install
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-integration --gate migrations --no-install
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --gate backend-static --no-install
git diff --check
```

| Check | Result |
|---|---|
| Backend-unit | 282 passed, one existing warning, 13.46s. Log `.local-t8-unit.log` (ignored). |
| Full backend-integration | 320 passed, 928 existing warnings, 429.46s; no model drift. Log `.local-t8-validation.log`. This run collected seven initial T8 cases; the final nine-case focused run below adds concurrency/worker sequence and strengthens retention coverage. No implementation change followed the full run. |
| Final focused T8 | 9 passed, 27 existing warnings, 16.80s, followed by no model drift. Includes real worker process startup/shutdown and resumed writes. Log `.local-t8-focused-final.log`. |
| Migrations | Passed clean and seeded upgrades to sole head `c3d8e1f52a74`, unchanged legacy business snapshots/untracked/unprocessed defaults, custom-format backup/restore, production CLI init/rerun/rebuild/reconcile, retained maintenance downgrade guard, all earlier history guards and empty downgrade/re-upgrade. Log `.local-t8-validation.log`. |
| Baseline/static | Compose config, installed dependency consistency, candidate secret scan, Ruff lint/format (227 files), mypy (161 sources) passed. Log `.local-t8-final-checks.log`. Separate Ruff check/format of changed migration verifier passed. |
| Offline migration SQL | `alembic upgrade b2c7d9a41e63:c3d8e1f52a74 --sql`, using an inert loopback port-1 test URL and generated test settings, passed. Reviewed one additive table, scope FK, kind/reason checks and unique partial initialization index; no business rewrite. |
| Diff whitespace | Passed. |

The focused invocation used `validate.services(False)` and
`disposable_database(prefix='restaurantos_t8_final', test_url=env['TEST_DATABASE_URL'])`.
Its guarded `database.environment(env)` supplied both `DATABASE_URL` and
`TEST_DATABASE_URL`, then ran from `backend/`:

```text
python -m alembic upgrade head
python -m pytest tests/integration/test_event_maintenance.py -q --tb=short
python -m alembic check
```

All successful service runs completed disposable database/Compose cleanup. The
backup/restore archive exists in memory for the disposable rehearsal; the
application runbook separately saves a durable backup before any real cutover.
Local rehearsal used tools inside its owned PostgreSQL container. External-service
CI requires compatible `pg_dump`/`pg_restore` on PATH; that external path was
inspected but not executed locally.

## Earlier attempts and corrections

- Sandbox denied Docker's named pipe; reran with the approved validation
  exception. The sandbox unit run stalled in the existing Windows unit socket
  guard; interrupted it and the outside-sandbox unit gate passed.
- Initial focused run: six passed, one failed because the test expected
  `ValueError` instead of inventory's existing scoped `NotFoundError`. Corrected
  that assertion. A later strengthened test supplied only the failing analytics
  handler; the fixed registry correctly rejected it. Corrected test wiring to
  retain all registered consumers. Final focused run passed.
- Initial static checks found formatting and union-variable type issues in new
  code. Corrected before the final passing static gate.
- Secret scanning classified public Alembic revision strings as high entropy;
  added narrow inline false-positive annotations, including the formatter-moved
  revision argument. Final scan passed without broad exclusions.

These failed/partial attempts are not counted as acceptance evidence.

## Limits and remaining operations

No live application migration, initialization, backup/restore or rollout was
executed. The separate cutover must inspect the actual current application
revision and verify its backup first. `--maintenance-confirmed` is an operator
attestation, not a mechanism that stops arbitrary writers/workers; the required
offline precondition remains operational. Maintenance is atomic per scope,
not across every restaurant in an organization. An ambiguous rebuild response
can produce another provenance record on retry, while reconstructed totals stay
the same. Initialization reruns retain their original marker.

Frontend tests/static/build, browser, runtime image and remote CI were not run:
this slice changes no frontend, HTTP contract, dependency or image. Committed
dependencies were not reinstalled or resolved. Full ten-gate M8 acceptance and
freshness evidence remain T9–T11. No pruning or external notification delivery
was introduced. Historical T7 application-revision evidence is not a new current
database inspection. User-authorized delivery is a local commit only; no push,
PR creation or GitHub issue state change is part of this task.
