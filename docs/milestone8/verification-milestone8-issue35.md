# Milestone 8 issue #35 verification

Implemented: 2026-10-13 (UTC); final verification: 2026-10-14 (UTC). Base: `316de52` (merged issue #34). Verified working-tree
implementation before the requested branch commit; no push, PR, remote CI or
application migration performed.
Authoritative source: [approved design revision 1](milestone-8-design.md), T5 in
[the task plan](milestone-8-task.md), and GitHub issue #35.

## Scope and agreed choices

- Fixed-registry execution service owns short persisted attempt claims and atomic
  effect/receipt/success transactions. Row locks, unique receipt constraints and
  claim tokens fence duplicates and stale workers; ACK follows commit.
- Actual analytics, alert and sink feature handlers remain #36–#37, per the user.
  Missing handlers stay pending without placeholder receipts or spent attempts.
  Integration/process tests use code-wired test handlers with real DB effects.
- Eight charged attempts by default (`EVENT_WORKER_MAX_ATTEMPTS`, range 1–100).
  Persisted exponential retry starts at one second, with accepted 0–10% positive
  jitter and a 60-second final cap. Original T4 lease/pool/scan budgets are reused.
- User accepted counting durably started interrupted attempts. Shared outages
  retain diagnostic history but refund the charged allowance. History ordinals
  remain unique even after refunds; replay starts a new cycle without deletion.
- Trusted `python -m app.modules.events.cli status|inspect|replay`; replay requires
  one failed delivery UUID and a reason, with PostgreSQL `session_user` provenance.
  No free-form actor confers authority. Original correlation and replay UUIDs are
  retained. Safe output omits payloads, free-form reasons and raw exceptions.
- T5 uses the existing T1 tables and migration head `b8f34c2a91de`; no schema,
  HTTP API, frontend, dependency lock or runtime-image changes.

## Verification

Environment: Linux cloud workspace, Python 3.12.14, disposable PostgreSQL 16 and
Redis 7 Compose projects. Committed hashes installed with:

```bash
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-dev.txt
```

| Command from repository root | Result |
|---|---|
| `backend/.venv/bin/python scripts/validate.py --gate baseline --gate backend-unit --gate backend-static --no-install` | Passed: Compose configuration, locked dependency consistency, candidate secret scan, 280 unit tests, Ruff lint/format, mypy (146 application sources). |
| `backend/.venv/bin/python scripts/validate.py --gate backend-integration --no-install` | Passed: 286 tests, including the final driver-authentication redaction regression; `alembic check` reports no model drift. |
| Historical focused disposable PostgreSQL/Redis run of `tests/integration/test_event_execution.py` and `tests/integration/test_event_worker.py` | Passed: 26 tests. |

The first static attempt found Redis dependencies missing from the prebuilt
virtualenv; installing committed requirements resolved it. The first full
integration run had 281 passes and two failures: the new crash test exposed a
pending entry reclaimed before lease expiry that was never rechecked by its
current owner, and an existing fault-injection test still patched the old routing
boundary. Pending recovery now rechecks all sufficiently idle entries, including
self-owned entries, and the fault injection targets the new execution boundary.
The focused rerun and then the full 285-test integration gate passed. Final
review added safe handling for raw driver errors during connection setup and a
CLI authentication-error redaction regression. The final 2026-10-14 run passed
all 286 integration tests and the drift check; 835 existing deprecation warnings
were emitted. The final unit run passed 280 tests with one existing warning.
The raw integrity SQLSTATE extension was also checked in the final unit/static
run. Logs are retained locally as `issue35-final-checks.log` and
`issue35-final-integration.log` (ignored by Git).
The baseline secret scan initially flagged intentionally fake credential URLs
used in redaction tests. Explicit inline test-data allowlists resolved those
false positives without changing the repository secret baseline.

## Acceptance evidence

| Requirement | Executable evidence |
|---|---|
| Atomic effects, unique receipts, overlapping duplicates | Barrier holds the first transaction after effect/receipt flush; competing real `FOR UPDATE SKIP LOCKED` cannot process it. Only one effect and receipt commit. Failure after effect staging rolls it back; deliberate skips receive receipts. |
| Crash before effect commit / after commit before ACK | Actual worker subprocesses are killed at both barriers and restarted. Precommit death retries with an interrupted attempt; postcommit death produces no second effect. All pending references eventually ACK. |
| Retry bound, restart and independent consumers | Deterministic clocks exercise eight failures, each persisted due time and fresh service instances. Analytics success survives sink poison/replay without rerunning. Separate Redis group loops test shared-dependency isolation and ambiguous ACK. |
| Infrastructure versus event failure | Ten shared outages retain history without spending allowance; real PostgreSQL connection termination rolls back effects and settles the refund after reconnect. Constraints stay local to one delivery. |
| Authoritative references and contracts | Missing/conflicting references create no effect/attempt. Unsupported versions and invalid stored payloads fail immediately and remain inspectable. Test-only DDL restores guards in disposable databases. |
| Fencing and interrupted-attempt limit | Expired claims recover through PostgreSQL; an old token cannot write after replacement. Restart at the configured limit fails the delivery without an effect. |
| Operator status, replay and redaction | Real CLI subprocesses return safe status/inspect, replay exactly one failed delivery, reject invalid/already replayed/successful targets, retain attempts and other receipts, and record authenticated DB role/reason/time/replay UUID/original correlation. |
| Correlation and privacy | Allowlisted attempt/cycle/replay fields; unsafe category/identifier redaction; payloads, Redis credentials and driver text are absent from CLI output. |

## Final policy confirmation

On 2026-10-14 the user accepted immediate failure for event-caused integrity
violations (`event_constraint`). Serialization/deadlock failures remain retryable.
All implementation policy questions raised for T5 are resolved.

## Limits and omissions

Full milestone acceptance remains open. T6/T7 effects, maintenance, frontend,
measured freshness and full remote CI are not claimed. Frontend, browser,
migration and image gates were not run for this backend-only, schema-free slice.
The backend integration gate migrates only disposable test databases and checks
model drift. It never migrates the application database or removes developer data.

Shared database credentials identify an operator role, not a human; separate
operator roles are needed for individual attribution. If a process dies while
PostgreSQL is unavailable before failure classification can be persisted,
recovery can only identify an interrupted attempt; the agreed crash rule applies.
No automatic database history deletion or Redis trimming is introduced.
