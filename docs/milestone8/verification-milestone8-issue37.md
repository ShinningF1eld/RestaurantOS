# Milestone 8 issue #37 verification

Reviewed: 2026-10-15 (Asia/Bangkok). Baseline: `9bec41e` plus the uncommitted
issue #37 working tree. Sources: [issue #37](https://github.com/ShinningF1eld/RestaurantOS/issues/37),
[approved design revision 1](milestone-8-design.md), [T7 criteria](milestone-8-task.md#t7-project-alert-history-and-deduplicated-notification-and-diagnostic-records),
ADRs 0001/0002, and current inventory/event contracts. The design is authoritative.
Environment: Windows, Python 3.12.13, disposable PostgreSQL 16 and Redis 7.

## Result and scope

The focused implementation review found no remaining actionable defects against
the six issue criteria. All 16 focused tests and clean/seeded migration checks
passed. Final full backend integration passed 313 tests with no model drift.
This is an implementation-agent review; the requested independent review remains
separate. No commit, push, PR, or GitHub issue mutation was performed.

Alerts own episode history and current revision state. Notifications own actual
durable stub/skip/suppression outcomes and order/menu diagnostic records. The
fixed consumer registry calls both public services inside T5's effect/receipt/
delivery transaction. Public inventory interfaces supply authoritative state,
episode snapshots and the shared restaurant lock. Trusted scoped inspection and
rebuild hooks prepare T8/T9 integration. No HTTP route, frontend, external
provider, dependency, or runtime image change is included.

## Acceptance criteria

| Issue criterion | Status | Evidence |
|---|---|---|
| 1. Opening/resolution snapshots and provenance, including close-before-open and rename/archive | Passed | Real producer/API facts consumed in reverse order; original name, unit, opening quantity/threshold, actor/source and archive resolution survive rename, restoration, and rebuild. `_store_episode_facts` copies all producer opening/closing facts, including optional order provenance. |
| 2. Revision fencing and no stale reopening/reminders | Passed | Current state loads the authoritative revision under the restaurant lock; older queued events cannot replace it. Two-episode supersession test preserves the later active identity while filling older history. Repeated low deductions and rename emit no extra low episode. |
| 3. Unique stub, authoritative stock check and atomic receipt | Passed | Unique episode constraint; live active/low/identity checks under the stock restaurant lock. Concurrent duplicate delivery sees a busy delivery or durable receipt. Real-effect rollback and actual worker termination before commit leave no partial effect/receipt; restart after commit/before ACK preserves one effect. No network operations in handlers. |
| 4. Durable skips/suppression and both timing boundaries | Passed | Resolved/superseded low events store skipped outcomes and receipts. Baseline suppression and provenance survive repeat rebuild. PostgreSQL `pg_blocking_pids` proves a sink waiting behind a resolving stock transaction; the reverse test holds the sink before commit and observes the real stock request blocked until its commit. Later replenishment retains the created stub and resolves history/current state. |
| 5. Durable deduplicated order/menu diagnostics | Passed | Submitted, accepted, completed, cancelled, deleted and menu events create event-keyed records; replay through execution leaves one record per UUID. Actual production worker entrypoint creates a diagnostic record. Inspection confirms allowlisted facts exclude customer names/notes and credentials; no external delivery or reminder/acknowledge/dismiss behavior is introduced. |
| 6. Rebuild, producer retention and safe schema | Passed | Repeat rebuild retains episode snapshots, notification outcomes and successful receipts; baseline source/suppression remain explicit. Source inventory facts remain intact. Models are registered. Offline SQL, clean/seeded upgrade, model drift and independent retained-data downgrade guards for all four tables were checked. Business ingredient/order identities do not cascade away on deletion; diagnostic test deletes the real order before consuming its facts. |

## Executed checks

Commands from repository root, using the existing committed-lock environment:

```powershell
.\backend\.venv-m6-dev\Scripts\python.exe scripts/validate.py --gate backend-unit --no-install
.\backend\.venv-m6-dev\Scripts\python.exe scripts/validate.py --gate backend-static --no-install
.\backend\.venv-m6-dev\Scripts\python.exe scripts/validate.py --gate backend-integration --no-install
.\backend\.venv-m6-dev\Scripts\python.exe scripts/validate.py --gate migrations --gate baseline --no-install
.\backend\.venv-m6-dev\Scripts\python.exe scripts/validate.py --gate migrations --no-install
.\backend\.venv-m6-dev\Scripts\python.exe scripts/validate.py --gate baseline --no-install
.\backend\.venv-m6-dev\Scripts\python.exe scripts/validate.py --gate baseline --gate backend-static --no-install
```

- Unit: 282 passed, one existing warning, 11.45 seconds. Log:
  `.local-t7-unit.log` (ignored).
- Static: Ruff lint/format passed; 224 formatted files; mypy passed 159 sources.
  The final combined baseline/static command also passed; log:
  `.local-t7-final-checks.log` (ignored). `git diff --check` passed.
- Focused: 16 passed, 43 existing warnings, 30.59 seconds, followed by a clean
  `alembic check`. The invocation used `validate.services(False)` and
  `disposable_database(prefix='restaurantos_t7_focused', ...)`, then ran
  `python -m alembic upgrade head`,
  `python -m pytest tests/integration/test_alert_projection.py -q --tb=short`,
  and `python -m alembic check` from `backend/`, with the guarded
  `database.environment(env)` assigning both database URLs. Log:
  `.local-t7-focused.log` (ignored).
- Final full integration: 313 passed, 908 existing deprecation warnings,
  426.80 seconds; `alembic check` reports no new upgrade operations. Disposable
  database and Compose cleanup completed. Log: `.local-t7-integration-final.log`
  (ignored).
- Migrations: all checks passed through sole head `b2c7d9a41e63`: clean upgrade,
  seeded legacy business-data preservation, empty-table downgrade/re-upgrade,
  model drift, and retained order/event/inventory/analytics guards. Each T7 table
  independently rejected destructive downgrade, preserving rows/schema/revision.
  The combined command subsequently failed its separate baseline scan because
  a public Alembic revision was classified as a secret. That false positive was
  marked explicitly. The separate final migrations command additionally passed
  a committed empty T7 downgrade and re-upgrade; it exited successfully.
  Baseline rerun passed Compose configuration, dependency consistency and
  candidate secret scanning. Logs: `.local-t7-migrations.log`,
  `.local-t7-migrations-final.log`, `.local-t7-baseline-final.log` (ignored).
- Offline SQL: from `backend/`, with an inert `DATABASE_URL` ending in
  `restaurantos_offline_test` on loopback port 1,
  `.\.venv-m6-dev\Scripts\python.exe -m alembic upgrade a936d8e4c021:b2c7d9a41e63 --sql`
  succeeded. Reviewed four additive tables, fixed-precision quantities,
  composite scope foreign keys, episode/event uniqueness, indexes and revision
  update; there is no business-data rewrite or seed.

Earlier diagnostic full integration: 299 passed, four failed (384.62 seconds).
The lock test confused the executor's `consumer_committed` result with the
persisted `skipped` receipt; the worker entrypoint still expected zero processing
attempts; two analytics crash barriers lost their test-handler environment flag.
Those assertion/test-wiring defects were corrected. History-only deliveries
also now take the restaurant lock, preventing first-insert races with state
deliveries; the explicit overlap regression passes. Intermediate static checks
caught CRLF introduced while editing two new files; targeted formatting and the
final static check passed. These failed attempts are not acceptance evidence.

## Application database incident

During the initial implementation on 2026-10-14, an ad hoc migration command set
only `TEST_DATABASE_URL`. Alembic correctly uses `DATABASE_URL`, so it fell back
to the configured application database and advanced it from `a936d8e4c021` to
`b2c7d9a41e63`. This was an accidental application migration, disclosed in the
chat before the pause. The additive revision created empty T7 tables; it did
not rewrite business rows. A subsequent read-only revision check confirmed
`b2c7d9a41e63`. No downgrade was attempted. No further application migration was
performed during the 2026-10-15 continuation.

All reported disposable validation uses the guarded environment assigning both
`DATABASE_URL` and `TEST_DATABASE_URL`; its databases and Compose resources are
removed on exit. Repository head and the incident's dated database observation
are distinct from rollout/initialization. Future application cutover must inspect
the actual revision and use the maintenance/backup procedure; T8 initialization
was not run against the application database.
The interrupted 2026-10-14 disposable project
`restaurantos-t7-14f8c6e0b6dd` was found still running after restart and explicitly
removed on 2026-10-15, including its test containers and network. The developer
database/volume was not part of that cleanup.

## Limits and next work

- T8 owns combined maintenance CLI/initialization orchestration; T9 owns
  authorized HTTP alert/history reads, pagination and frontend refresh behavior.
  Current internal hooks return scoped ORM rows for trusted callers and do not
  replace user-facing authorization.
- Frontend tests/static/build, browser, image and remote CI were not run for this
  backend/schema slice. Dependencies were not reinstalled. Full M8 freshness,
  cutover and all-ten-gate acceptance remain open.
- No automatic event/receipt/episode/sink pruning is introduced; retained storage
  grows. There is no external notification provider or exactly-once ordinary-log
  guarantee. The migration refuses downgrade while any T7 data remains.
- Independent review is still required before the user's intended commit.
