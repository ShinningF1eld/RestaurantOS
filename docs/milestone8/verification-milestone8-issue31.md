# Milestone 8 Issue #31 verification

Reviewed: 2026-10-11 (Asia/Bangkok)
Sources: [GitHub Issue #31](https://github.com/ShinningF1eld/RestaurantOS/issues/31), approved [Milestone 8 design revision 1](milestone-8-design.md), [Milestone 8 task plan](milestone-8-task.md), [master roadmap](../../RestaurantOS_Master_Roadmap.md), and [event API contract](../api/events.md).
Revision and local changes: reviewed the current working tree at `3dd7bb80887ef9e1b31b965b932bf50812ad82b6`; Issue #31 implementation changes are uncommitted.
Comparison base: current `HEAD`; no PR or committed implementation revision was supplied. Issue #31 records an earlier inspected baseline (`156badacb0dba913d3548389cb1c08d34316539b`).
Environment: Windows, Python 3.12.13, disposable PostgreSQL/Redis validation resources. The application database was not migrated.

## Result

The T1 implementation covers the approved event contracts, fixed subscription registry, caller-transaction append path, durable PostgreSQL records, order revision metadata, and additive migration. Static, focused contract, integration, and migration checks passed. One actionable contract defect remains: inventory contracts accept internally contradictory episode transitions. The full `backend-unit` gate also remains unverified because it stalls on the first auth unit test in this Windows environment. I would not treat Issue #31 as fully verified until the contract invariant is corrected and the required unit gate completes in a working environment.

## Criteria and coverage

| Requirement / criterion | Status | Evidence | Remaining gap |
|---|---|---|---|
| Issue #31: all eight approved versioned contracts, typed fields, trigger/no-op matrix, fixed subscription matrix | Passed | Inspected `backend/app/modules/events/domain/contracts.py`, `domain/subscriptions.py`, and `docs/api/events.md`; focused contract suite passed (6 tests). | No business producers or consumers are implemented in T1, as scoped. |
| Issue #31: envelope identity, version, scope, revision, UTC/correlation, decimal serialization, legacy order timestamp behavior, payload minimization | Passed | Code inspection; focused tests exercise decimal strings, version rejection, aggregate identity, and naive order `created_at` as UTC; PostgreSQL integration tests exercise restaurant/organization verification. | Event privacy is enforced by narrow typed payloads and `extra="forbid"`; no production producer exists yet. |
| Issue #31: immutable events, fan-out delivery state, unique receipts, retained attempts/replays, claim metadata, caller-owned transaction | Passed | `backend-integration`: 228 passed, including 5 event storage tests for rollback, scope, fan-out, receipt uniqueness, and survival after order deletion. Model/migration inspection confirms retained-history FKs/triggers and no independent repository transaction. | Redis relay/consumer runtime and attempt/replay operations are later issues and were not exercised here. |
| Issue #31: event payloads reject invalid state facts | **Failed** | Manual validation reproduced accepted contradictory `inventory.state_changed.v1` payloads; see finding below. | Require consistent low-state, episode ID, and opened/resolved transition invariants in both payload and producer transition types. |
| Issue #31: additive order revision and safe migration, constraints/indexes, single head, downgrade protection, no startup migration | Passed | `backend-static`, clean/seeded `migrations`, `alembic check`, and offline Alembic SQL inspection passed. `alembic heads` returned only `c61a0f3d9e42 (head)`. Migration tests verified populated legacy preservation and refusal to downgrade with retained event/history facts. Startup code contains no migration invocation. | None for the T1 schema criteria reviewed. |
| Issue #31 verification: `backend-unit` | **Untested** | Re-run collected 231 tests but stalled at `tests/unit/auth/test_admission.py`; it was interrupted without a test result. The existing T1 evidence attributes the Windows hang to the socket guard at `backend/tests/unit/conftest.py:50`. The new event unit module independently passed (6 tests). | Complete the full unit gate in an environment where the existing Windows Proactor socket guard does not hang. |

## Actionable findings

### P2: Inventory episode contracts accept contradictory state transitions

Location: `backend/app/modules/events/domain/contracts.py:165-177`; `backend/app/modules/inventory/domain/transitions.py:44-52`
Trigger: Construct an `InventoryStateChangedPayload` with `is_low=False` and `episode_transition="opened"`, or with `is_low=True` and `episode_transition="resolved"`. The producer-facing `InventoryTransition` also permits a low snapshot without an `episode_id`, and permits an opened transition whose computed state is not low.
Expected / actual: An opened transition should describe a resulting low state with an episode ID; a resolved transition should describe a resulting non-low state and its closing episode ID/reason. A low transition snapshot should carry the current episode ID. Actual: all of the contradictory combinations described above pass construction; the event service can then persist the invalid facts.
Impact: A later producer can durably record contradictory inventory state. Alert processing may open an alert while stock is not low, resolve an alert while stock remains low, or lack the episode identity needed for deduplication.
Evidence: Manual validation with the backend virtualenv printed `ACCEPTED (is_low=False, transition=opened)` and `ACCEPTED (is_low=True, transition=resolved)` for the event payload; an `InventoryTransition` with `is_low=True, episode_id=None` was also accepted.
Suggested correction: Add model-level cross-field validation requiring `opened` to have a low resulting state and episode ID, `resolved` to have a non-low resulting state plus episode ID/reason, and every low `InventoryTransition` snapshot to have an episode ID. Add focused regression cases for these rejected combinations.

## Executed checks

| Command or procedure | Conditions | Result |
|---|---|---|
| `backend/.venv-m6-dev/Scripts/python.exe -m pytest tests/unit/test_event_contracts.py -q` | Run from `backend/` | Passed: 6 tests. |
| `./scripts/validate.ps1 -Gate backend-static -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe` | Repository lock already installed | Passed: Ruff, formatting (183 files), and mypy (133 modules). |
| `./scripts/validate.ps1 -Gate backend-integration -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe` | Isolated disposable PostgreSQL/Redis Compose project | Passed: 228 tests; `alembic check` reported no new upgrade operations. |
| `./scripts/validate.ps1 -Gate migrations -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe` | Disposable clean and seeded legacy databases | Passed: clean and legacy upgrade, model drift, preservation, existing order-history downgrade guard, and retained event/delivery/history downgrade guard. Test databases and Compose resources were cleaned up. |
| `python -m alembic heads` | Run from `backend/` | Passed: one head, `c61a0f3d9e42`. |
| `python -m alembic upgrade e68d9a24b537:head --sql` | Offline SQL generated from `backend/` | Inspected generated order revision default, event/delivery/receipt/attempt/replay tables, composite restaurant/organization FK, due/claim indexes, and immutability trigger DDL. |
| `./scripts/validate.ps1 -Gate backend-unit -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe` | Windows Python 3.12.13 | Collected 231 tests and stalled at the first auth unit test; interrupted without test completion. No pass is claimed. |
| Manual inventory payload/interface validation | Backend virtualenv; no source or test files changed | Reproduced the contradictory accepted values described in the finding. |

## Limits and next actions

This review covers the T1 contract/storage slice only. No worker, Redis publication, business event emission, alert/analytics consumer, or frontend behavior was verified or expected in Issue #31. The new and existing event facts were tested only against disposable databases. The full `backend-unit` gate remains outstanding due to the observed host-level socket guard hang; the targeted event unit tests do not substitute for that gate. No source changes, issue/PR updates, commits, or application database migrations were made during this review.
