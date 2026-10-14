# Milestone 8 issue #36 verification

Reviewed: 2026-10-14 (Asia/Bangkok). Comparison base:
`ad7707019cbf3e6b204ad5acb4f7911c431bcfa1`; initially clean working tree.
Scope: uncommitted issue #36 implementation, reviewed by its implementing agent.
Sources: [GitHub #36](https://github.com/ShinningF1eld/RestaurantOS/issues/36),
[authoritative design revision 1](milestone-8-design.md), [task plan T6](milestone-8-task.md),
ADR 0002, current event/order contracts and T3–T5 implementation evidence.
Environment: Windows, Python 3.12.13, installed committed dependencies,
disposable PostgreSQL 16 and Redis 7 Compose projects.

## Implementation

- Analytics' public `service.py` stages completion/deletion effects inside T5's
  transaction. Pure contribution/revision rules live in `domain/projection.py`;
  scoped queries, joins and writes live in `repo/projection.py`.
- New contribution/tombstone and daily-total models live in analytics' repository.
  Order deletion cannot cascade their revision facts. Individual totals retain
  two decimals; `Numeric(20,2)` daily sums can exceed one order's maximum.
- The fixed consumer registry now installs the actual analytics handler. Alert
  and notification/sink handlers remain T7. A stale revision is a deliberate
  receipted skip; ACK still follows effect/receipt/delivery commit.
- A shared restaurant lock serializes same/different-order projection changes,
  including absent-row inserts, and fences maintenance. No network work occurs
  while holding it. This conservative approach reduces branch concurrency; no
  speedup or dashboard projection cutover is claimed.
- CLI `analytics-inspect` returns scoped daily/contribution rows;
  `analytics-reconcile` compares them to authoritative completed-order SQL and
  reports per-date discrepancies. Both require an explicit matching organization
  UUID/restaurant ID and use trusted database credentials, not user principals.
- `AnalyticsProjectionService.rebuild` seeds all live order revisions, including
  noncompleted zero-contribution watermarks, and retained deletion facts. It
  preserves receipts, delivery/attempt history and queued events. It aborts if an
  existing nondeleted contribution lacks both a live order and a deletion fact.
  Combined maintenance initialization/provenance/CLI remains T8; stop workers and
  quiesce business writes before using this interface.
- Additive migration `a936d8e4c021` follows `b8f34c2a91de`, creates two empty
  projection tables, and refuses downgrade while either has data. Composite
  scope FKs, primary keys and revision/state/money/count checks match metadata.
  No existing business rows are rewritten or backfilled by the migration.

## Acceptance review

All five issue #36 acceptance criteria passed through inspection and fresh
executable evidence. Final full integration: 297 passed, with no model drift.
No actionable T6 finding remains. Full Milestone 8 acceptance remains open.

| Issue criterion | Status | Evidence |
|---|---|---|
| 1. Creation-date, fixed-precision completed totals | Passed | UTC/legacy-naive unit cases; real SQL comparison across two tenants/restaurants, cancelled exclusion and a `100000000.01` daily sum; replacement across dates. |
| 2. Deletion tombstone, ordering, duplicates and replay | Passed | Both completion/deletion permutations; duplicate event UUID and distinct UUID at the same revision; terminal deletion rule; injected real-effect rollback followed by operator replay and SQL match. |
| 3. Atomic receipt/effect/deltas and concurrency | Passed | Fail after effect/receipt flush: no projection or receipt commits. Competing different/same-order events observed in PostgreSQL's actual lock wait graph, with one correct contribution per order. Actual worker processes killed before commit and after commit/before ACK, then production entrypoint restart. |
| 4. Scoped inspection/reconciliation; live dashboard | Passed | CLI subprocess detects deliberate discrepancy in one scope; foreign scope pair rejected and another branch stays matched. Existing dashboard service/routes/query implementation continues using live orders (inspection and existing analytics regression). |
| 5. Maintenance watermarks and safe schema | Passed | Repeat rebuild with successful receipts and queued older/deleted events; revision 7 contribution stays single, revision 5 deletion remains absent; missing authoritative fact aborts. Clean/seeded migration, model drift, preservation and each retained-table downgrade guard. |

## Commands and current results

Commands run from repository root unless stated otherwise; every selected gate
is partial repository validation, with locked installation omitted.

```powershell
./scripts/validate.ps1 -Gate backend-unit,backend-static -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
./scripts/validate.ps1 -Gate backend-integration,migrations -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
./scripts/validate.ps1 -Gate migrations,baseline -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
./scripts/validate.ps1 -Gate baseline,backend-unit,backend-static -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
./scripts/validate.ps1 -Gate backend-static -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
./scripts/validate.ps1 -Gate backend-integration -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
./scripts/validate.ps1 -Gate baseline,backend-static -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
```

- Unit gate: 282 passed, one existing warning, outside the restricted socket
  environment. Latest static gate: Ruff lint/format passed, mypy passed 149 sources.
- Final backend-integration gate: 297 passed, 866 existing deprecation warnings,
  310.26 seconds; `alembic check` reports no new upgrade operations. Owned
  PostgreSQL/Redis services and databases were cleaned up on exit. Final log:
  `issue36-integration-verified.log` (ignored).
- Migrations gate: clean and representative seeded legacy upgrade passed through
  the unique new head, with no model drift, preserved business data and guarded
  downgrade/re-upgrade. Each analytics table independently blocked destructive
  downgrade without changing rows/schema/revision; existing retained event,
  inventory episode, stock and replay guards passed too.
- Baseline gate: dependency consistency, Compose configuration and candidate
  secret scan passed after explicit allowlists for public Alembic revision IDs.
  A later combined run reached unit/static; format checking caught CRLF in two
  edited files. Those were formatted and the separate static rerun passed.
- From `backend/`, `./.venv-m6-dev/Scripts/python.exe -m alembic upgrade
  b8f34c2a91de:a936d8e4c021 --sql` passed. Reviewed generated SQL: only two new
  tables, scoped restrictive FKs/checks/PKs and revision update in a transaction.
  Offline SQL generation does not connect to or migrate the application database.
- `git diff --check` passed.

Focused command from `backend/`, using the same interpreter with the repository's
`validate.services(False)` and `disposable_database` helpers to supply isolated
service configuration (upgrade head before tests, `alembic check` afterward):

```text
python -m pytest tests/integration/test_analytics_projection.py tests/integration/test_event_worker.py::test_consumer_groups_route_independently_reclaim_own_pel_and_rebuild_stream
```

Result: 12 passed, 33 existing warnings; no drift. Logs are retained as ignored
`issue36-focused.log`, `issue36-checks.log` and integration-run `.log` files.

## Earlier failures and corrections

The first restricted unit run stalled in the previously documented Windows
async socket guard and was interrupted. The same interpreter passed outside
that restriction. Docker test gates likewise ran outside the restricted pipe
environment, against independently named disposable services only.

The first integration run had 286 passes and eight failures. A new standalone
CLI test and worker process tests exposed incomplete SQLAlchemy mapper
registration introduced by the analytics imports. Repository queries now load
the existing shared model registry, without importing FastAPI or requiring a
running API. Analytics use cases were placed in the feature's `service.py` per
ADR 0002. The first auth outage test also failed because six quota attempts
straddled a fixed-window boundary (10:52:59–10:53:00 UTC); it passed on the next
run without changing authentication behavior.

The second integration run passed 296 tests and failed only the old T4 group
test, which expected analytics to remain unimplemented/pending. Updated test
expectations now prove analytics succeeds/ACKs once while the unfinished sink
is reclaimed and republished after Redis loss. Its analytics receipt is retained.
The final run also extends the rollback test through actual failed-delivery
operator replay and reconciliation using the installed analytics handler.

The third complete run passed 295 tests and failed the same group test's
remaining exact-two-publications assumption, plus the existing disabled-account
quota test's five-failure bucket assertion. A valid shared stream reference can
complete analytics before its relay turn, leaving either one or two initial
entries. The group test now observes that actual count, proves ownership recovery
for every sink pending entry, and expects only the unfinished sink to republish
after Redis loss. A focused disposable run passed all 12 analytics/group cases
with 33 existing warnings and no Alembic model drift. The disabled quota failure
was intermittent; its exact boundary timing was not recorded in that run, so
attribution to the same fixed-window behavior is an inference, not a reproduction.

The fourth full integration run passed every test, including both earlier auth
cases and the revised transport test. No auth source, quota, timeout or assertion
was changed. A final baseline/static run after the acceptance documentation
updates passed dependency consistency, Compose configuration, candidate secret
scan, Ruff lint/format and mypy. Its ignored log is `issue36-final-checks.log`.

## Limits

No commit, push, GitHub mutation, remote CI or application database migration.
Frontend tests/static/build, browser and image gates are omitted: no frontend,
HTTP contract, image or dependency changes. Combined initialization/rebuild
operations, alert/sink effects, load/freshness measurements and full M8 acceptance
remain later tasks. Inspection output currently reads the retained branch range;
M8 introduces no automatic retention/pruning. Migration application requires
the documented backup/maintenance procedure and is not authorized by validation.
