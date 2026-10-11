# Milestone 8 Issue #31 verification

Reviewed and fix verified: 2026-10-11 (Asia/Bangkok).

**Current result: P2 resolved.** AC1 now passes with the new invariant regressions; AC2-AC5 retain their scoped review passes. The fix passed backend-static, 259 unit tests and 234 PostgreSQL integration tests with no model drift. Historical review evidence is retained below and superseded by the fix follow-up. Full Milestone 8 acceptance remains open.

Sources: [GitHub Issue #31](https://github.com/ShinningF1eld/RestaurantOS/issues/31) and its comments (read live; no comments), approved [Milestone 8 design revision 1](milestone-8-design.md), [task plan T1](milestone-8-task.md), [master roadmap M8](../../RestaurantOS_Master_Roadmap.md#milestone-8--reliable-background-jobs-and-domain-events), [event API contract](../api/events.md), README/current-state, ADRs 0001/0002, and the testing/migration procedures.

Pre-fix inspected revision: `6a9c3a63583252bc1600bb7648ef4067ce8ae1ad`; working tree was clean before review. T1 is committed in `44a518b`; HEAD also includes T2 inventory episodes. Review scope is the current T1 contract/storage behavior and its producer interfaces, not a full T2 or Milestone 8 acceptance review. No PR was supplied. Event-module code is unchanged between the T1 commit and reviewed HEAD. Historical issue/design inspection revisions are not the reviewed implementation revision.

Environment: Windows, Python 3.12.13 (`backend/.venv-m6-dev`), locked dependencies already installed, disposable PostgreSQL 16/Redis 7 resources. The application database was not migrated.

## Pre-fix review result

Issue #31 is **not fully satisfied**: the contract/storage structure is present, but inventory contracts still accept contradictory episode facts (P2 below). All eight event types round-trip and reject extra payload fields; existing event contract tests pass without testing these contradictions. The required full unit gate now passes outside the sandbox, replacing the earlier incomplete unit evidence.

All four required gates passed: backend-unit (243 tests), backend-integration (234 tests, including five event storage tests, with model-drift check), backend-static, and clean/seeded migrations with retained-history downgrade guards. The implementation finding remains despite those passes. Coverage: AC1 failed in part; AC2-AC5 passed within the T1 scope and evidence limits below.

GitHub currently marks #31 closed as completed, although its five acceptance checkboxes remain unchecked. The local task plan marks all five checked; the previous verification report records a contract defect and incomplete unit validation. Closure/checkmarks do not establish acceptance. This report records fresh evidence without changing GitHub or other documents.

## Pre-fix acceptance criteria and coverage

Statuses below refer to the five actual GitHub acceptance criteria. Passing inspection establishes the T1 interface/schema scope only; later worker behavior is outside this issue.

| ID | GitHub acceptance criterion | Status | Evidence and limits |
|---|---|---|---|
| AC1 | Eight typed contracts; documented trigger/no-op and fixed subscription matrices | **Failed (partial coverage passed)** | All eight definitions exist in `events/domain/contracts.py`. `docs/api/events.md` records fields/triggers/no-ops and matches `domain/subscriptions.py`. Six focused tests pass; manual round-trip and extra-field rejection pass for all eight types. Inventory episode semantics remain contradictory; see P2. Actual emission/no-op behavior belongs to #33. |
| AC2 | UUID/type/version, verified tenant scope, aggregate identity/revision, UTC/correlation, lossless decimals, legacy creation date, minimized payloads | Passed | Typed envelope/identity validators, bounded safe correlation IDs, lossless decimal serializers, explicit naive creation-time UTC interpretation, and forbidden extra fields inspected. Focused tests verify money, version rejection, identities and legacy date grouping; manual checks cover all event round-trips and quantity strings. Scope is verified by `append_event` and the composite restaurant/organization FK. Monotonic revision assignment during event production belongs to later producer work. |
| AC3 | Immutable outbox; deliveries/receipts/attempts/replays/claims; atomic public append within caller transaction | Passed | `append_event` requires an existing transaction, checks scope and flushes event plus fixed fan-out without commit/rollback. Models and migration define receipts keyed by consumer/event, attempt/replay history and claim fields. The five storage tests passed in the 234-test PostgreSQL integration gate and cover successful fan-out, caller rollback, fan-out uniqueness failure rollback, scope/transaction rejection, receipt uniqueness and order-deletion survival. Runtime claiming/retry/replay services are #34/#35. |
| AC4 | Scope/identity constraints, retained history on business deletion, authoritative PostgreSQL payload/fixed dispatch | Passed | Composite scope FK, delivery uniqueness, receipt-to-delivery FK, attempt/replay FKs and retention triggers inspected. No event FK targets orders/menu items/ingredients; retained references use RESTRICT. Registry is a mapping proxy of fixed consumer tuples; this slice has no Redis dispatch or payload ingestion. Order deletion survival passed in the PostgreSQL suite; menu/ingredient deletion survival follows schema inspection, not a separate executed deletion scenario. |
| AC5 | Safe order revision defaults/snapshots, additive migration, SQL/index/downgrade review, one head, no startup migration | Passed | Orders receive non-null revision default 1 and a positive check without rewriting snapshots. Metadata registers event models. Offline T1 SQL reviewed, including scope/history FKs, due/claim indexes and triggers. Downgrade rejects any retained event/delivery/receipt/attempt/replay or advanced order revision. Current single head is `b8f34c2a91de` (T2), whose predecessor is T1 `c61a0f3d9e42`. API lifespan contains no migrations. Clean/seeded upgrades, model drift, snapshot/default preservation and order/event/inventory-history downgrade guards passed in disposable databases. |

## Actionable finding

### P2: Inventory event and producer contracts accept contradictory episode facts (fixed in follow-up)

Locations: `backend/app/modules/events/domain/contracts.py:166` (state validator), `:180` (low-stock payload), and `backend/app/modules/inventory/domain/transitions.py:135` (producer transition validation).

Requirement: AC1's typed contracts, the approved event trigger matrix, and design R8 define opening on entry into active stock at or below threshold and resolution when that predicate becomes false. Emitted low-stock episode identity must be stable and sufficient for later deduplication/history.

Pre-fix trigger and actual behavior: fresh Python 3.12 validation accepted each of the four cases below. The state examples satisfy the existing quantity/active `is_low` predicate, so they demonstrate the missing episode invariants rather than bypassing that predicate.

| Constructed contract | Accepted contradictory values |
|---|---|
| `InventoryStateChangedPayload` | Active, quantity `10.000`, threshold `5.000`, `is_low=False`, an episode UUID, `episode_transition="opened"`. |
| `InventoryStateChangedPayload` | Active, quantity `2.000`, threshold `5.000`, `is_low=True`, an episode UUID, `episode_transition="resolved"`, `resolution_reason="stock_recovered"`. |
| `InventoryLowPayload` | Opening quantity `10.000` above threshold `5.000`, with a valid episode UUID and aware opening timestamp. |
| `InventoryTransition` | Active quantity `2.000` at threshold `5.000`, with no episode identity. |
| `InventoryTransition` | Active quantity `10.000` above threshold `5.000`, with matching episode/transition UUIDs and an `opened` transition. |

Expected: opened transitions require a resulting low state and episode ID; resolved transitions require a resulting non-low state and closing episode ID/reason. Emitted low-state payloads require episode identity; producer snapshots of legacy low rows may intentionally lack one before maintenance initialization. Low-episode opening quantity must be at or below its threshold.

Impact: a later producer can submit validated but contradictory facts through the public append path; that path serializes them without additional episode validation. Consumers could open alerts when stock is normal, resolve alerts while stock remains low. This is a durable-contract defect, not demonstrated corruption of the current T2 inventory writer: that writer computes boundaries using `low_episode_transition`, and no business event producer exists yet.

Attribution: state/low-payload validators are unchanged since T1 commit `44a518b`. The producer interface has since expanded in T2 but still lacks these cross-field checks. The existing six event unit tests do not cover these invalid combinations; all pass.

The previous report also classified a low producer snapshot without an episode ID as defective. That concern is withdrawn: `inventory/service.py` explicitly preserves legacy low rows without inventing episodes before baseline initialization. The accepted no-ID construction was reproduced, but is not counted among the four contract contradictions above.

Suggested correction: enforce opened/resolved state relationships in event payload validators and the public producer transition type, and opening quantity/threshold consistency in the low-stock payload; add focused rejection regressions alongside valid zero-threshold, archive/recovery and continued-low examples. The subsequent authorized fix applies these guards and regressions; see follow-up evidence below.

## Pre-fix executed checks

Commands use the repository root unless otherwise noted. The virtual environment is selected explicitly; no dependency installation or resolution was performed.

| Command / procedure | Current result |
|---|---|
| `./scripts/validate.ps1 -Gate backend-unit -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe` | **Passed: 243 tests**, one existing Starlette/httpx deprecation warning. Initial sandbox run collected 243 tests and stalled at the first auth unit test; interrupted. The same gate outside the sandbox completed in 11.05 seconds. The previous report's socket-guard cause is not established for current code; this run demonstrates sandbox dependence. |
| `./scripts/validate.ps1 -Gate backend-static,backend-integration,migrations -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe` | Initial sandbox attempt failed before gate execution because Docker pipe access was denied. Approved execution outside the sandbox created only disposable test resources. Static passed: Ruff lint, format check (185 files), mypy (133 source files). Integration passed 234 tests and its Alembic drift check. Migrations passed clean/seeded upgrades, retained legacy snapshots/defaults, and order/event/inventory-episode downgrade guards; no model drift. Disposable databases and Compose containers/network were cleaned up. Combined command exited 0. |
| `.venv-m6-dev/Scripts/python.exe -m pytest tests/unit/test_event_contracts.py -q` from `backend/` | **Passed: 6 tests** in 0.11 seconds. |
| `.venv-m6-dev/Scripts/python.exe -m alembic heads` from `backend/` | **Passed:** one head, `b8f34c2a91de`. This is repository graph evidence, not the application database revision. |
| `.venv-m6-dev/Scripts/python.exe -m alembic upgrade e68d9a24b537:c61a0f3d9e42 --sql` from `backend/` | Offline SQL generation succeeded; reviewed T1 DDL/defaults/constraints/indexes/triggers. No database migration was executed by this command. |
| Inline Python through stdin using the same interpreter from `backend/` | All eight envelopes passed serialize/deserialize equality and rejected an extra `customer_notes` field. Printed fixed subscriptions matched documentation. |
| Inline Python inventory payload/interface construction through stdin | Reproduced the four accepted contradictions above, plus the intentional legacy low/no-episode snapshot described separately. No source/test files were created. |

## Pre-fix scope and limitations

This report replaces the earlier uncommitted-T1 revision and stale single-head/count evidence with current checkout evidence. The earlier report's 228 integration tests and incomplete unit result are historical, not the results of this review.

No frontend, browser, image, baseline, or full ten-gate Milestone acceptance was run: those are outside the T1 verification command set. Worker recovery, consumer effect/receipt atomicity, claim fencing, retries/replay, analytics projections, alerts, sink behavior, initialization and freshness remain later issues. Schema inspection establishes menu-item/ingredient event retention and several history protections; the five event integration tests do not individually exercise every trigger, claim constraint or business deletion type.

The original report-only review modified only `docs/milestone8/verification-milestone8-issue31.md`. No implementation fixes, issue/PR writes, commits, pushes, or application migrations are part of this review. Issue #31 should not be considered fully accepted until the contract finding is corrected and the affected regression checks pass. Full Milestone 8 acceptance remains open independently.

## P2 fix follow-up — 2026-10-11

The user authorized implementation and a commit after the review. The fix is
based on `6a9c3a63583252bc1600bb7648ef4067ce8ae1ad` and includes the preceding
verification-report update. The earlier review and accepted-value reproductions
above describe the pre-fix code.

`InventoryStateChangedPayload` now rejects opened transitions when the resulting
state is not low and resolved transitions when it remains low.
`InventoryLowPayload` rejects opening quantities above their threshold.
`InventoryTransition` rejects contradictory opened/resolved producer boundaries,
while preserving low legacy snapshots without an episode ID before initialization.
Existing identity/reason checks remain in force. No schema, migration, endpoint,
subscription, event-version, or payload-field changes are introduced; validation
is stricter for invalid event facts.

Sixteen new unit regression cases cover contradictory active/inactive opens,
resolved-while-low payloads and producer boundaries, rejection at deserialization,
opening quantity above threshold, and valid zero/equal-threshold opens,
continued-low state, recovery, threshold change, archive and legacy snapshots.
The API contract documents these relationships.

| Fix command / check | Result |
|---|---|
| `.venv-m6-dev/Scripts/python.exe -m pytest tests/unit/test_event_contracts.py tests/unit/test_inventory_transitions.py -q` from `backend/` | Passed: 34 tests (18 event, 16 inventory transition), 0.14 seconds. |
| `./scripts/validate.ps1 -Gate backend-static,backend-unit,backend-integration -NoInstall -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe` | Backend static passed (Ruff lint/format and mypy); full backend-unit passed 259 tests. Backend-integration passed 234 tests (220.75 seconds) and Alembic reported no new upgrade operations. Disposable databases and Compose resources were cleaned up; command exited 0. Existing deprecation warnings remain. |
| `git diff --check` | Passed. |

Validation uses Python 3.12.13 and disposable PostgreSQL/Redis outside the sandbox
so Docker and Windows event-loop socketpairs are available. Migration-gate
execution is retained from the preceding review; it was not repeated for this
validator-only fix, which changes no schema or migration. Frontend/browser/image
and full Milestone acceptance remain outside this fix's scope. The application
database is not migrated.