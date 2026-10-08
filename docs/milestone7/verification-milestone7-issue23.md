# Milestone 7 issue #23 verification

Reviewed: 2026-10-08
Branch: `milestone7`
Base revision: `1d97a18` (`docs: organize milestone evidence and record issue 22 completion`)
Environment: Windows, Python 3.12.13; disposable PostgreSQL 16 and Redis 7 via the repository validation runner.

## Result

Issue #23's catalog invalidation behavior is implemented and verified. Existing
menu-list and menu-item-list keys are invalidated with targeted Redis `DEL`
commands only after their service-owned PostgreSQL transaction commits. Redis
invalidation failures produce a safe structured warning and leave successful
business writes successful. No schema, public URL, response contract, worker,
event, or outbox change was introduced.

The approved revision 12 design caches exactly two list endpoints. The GitHub
issue's broad phrase “list and detail payloads” is implemented for the cached
lists; menu and menu-item detail endpoints remain uncached as the approved design
requires. No detail cache keys were introduced.

## Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Invalidate only affected catalog keys after successful commit | Pass | API/Redis integration covers menu create/update/delete and item create/update/hard-delete/deactivation. Unrelated key remains present. Each mutation's next list read returns current database values. Menu deletion uses one targeted `DEL` for the restaurant list key and deleted menu item-list key. |
| Audit/flush/constraint/commit failure rolls back without invalidation; Redis failure cannot fail a committed write | Pass | Integration injects audit failure, repository flush `IntegrityError`, and SQLAlchemy `before_commit` failure; state remains unchanged and no `DEL` occurs. A classified Redis command failure after commit is logged and the create request succeeds. |
| Both `delete_menu_item` outcomes invalidate after commit | Pass | API integration exercises hard deletion with no order history and deactivation after order creation; both clear the item-list key. The order's saved item name and fixed-precision price remain unchanged after deactivation. |
| Invalidation/fill race remains within the source-read absolute age; failures safely observable | Pass | Deterministic event-controlled unit race runs for both list types: the old fill waits until post-commit `DEL`, then writes with only 500 ms remaining from its original 10-second deadline. Unit cases verify timeout, connection, and command failure logs omit keys and do not open the read circuit. |
| Fixed-precision prices, order snapshots, inventory/order locks, and no worker/outbox | Pass | Item-list integration confirms decimal string `5.20` / `18.99`; historical-order integration preserves the original item name and `7.40` price. Existing inventory/order concurrency and lock regressions pass in the full backend integration gate. Diff adds no worker, event, or outbox. |

Recipe and inventory stock changes do not invalidate the list keys because the
cached item payload excludes live stock/recipe availability fields.

## Executed verification

Commands ran from the repository root, using the installed locked environment and
`--no-install`:

| Command | Result |
|---|---|
| `backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-unit --no-install` | Passed: 188 tests, 1 existing Starlette deprecation warning. |
| `backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-integration --no-install` | Passed: 201 tests, 636 existing deprecation warnings. Disposable PostgreSQL/Redis services were removed. The runner's `alembic check` reported “No new upgrade operations detected.” |
| `backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-static --no-install` | Passed: Ruff lint, format check (160 files), and mypy (122 source files). |

These are the three requested backend gates, not full repository or Milestone 7
acceptance. Frontend, browser, migrations rehearsal, image, baseline/secret scan,
remote CI, and full Milestone 7 verification were not run for this issue. The
integration gate migrated only its disposable database; the application database
was not touched.

## Scope and remaining limits

The existing 10-second absolute source-read age remains the stale-data bound if
invalidation fails or an old fill races a committed write. No distributed lock or
schema migration is needed. Authentication rate limiting and full Milestone 7
acceptance remain separate work.
