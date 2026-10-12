# Milestone 8 Issue #32 verification

Reviewed: 2026-10-11 (Asia/Bangkok).

**Result: Issue #32 satisfies all five acceptance criteria within T2 scope.**
This review checks current behavior against the five GitHub acceptance bullets.
Full Milestone 8 acceptance remains open.

## Scope and sources

Reviewed HEAD: `f5cff37e5aa02128a937f0389a2cc92d4c7b0bd2`; working tree was clean
at review start. T2 landed in `6a9c3a6`; HEAD includes the subsequent inventory
episode contract fix. No PR/comparison base was supplied: this is a review of
current implementation, not attribution of defects to a new diff. Only this
report is modified; source, tests, configuration and GitHub state are unchanged.

Sources:

- [GitHub #32](https://github.com/ShinningF1eld/RestaurantOS/issues/32), fetched
  live with comments: closed as completed, no comments, five unchecked boxes.
- [Dependency #31](https://github.com/ShinningF1eld/RestaurantOS/issues/31), also
  closed, and its [contract-fix report](verification-milestone8-issue31.md).
- Approved [M8 design revision 1](milestone-8-design.md),
  [task plan T2](milestone-8-task.md), and
  [master roadmap M8](../../RestaurantOS_Master_Roadmap.md#milestone-8--reliable-background-jobs-and-domain-events).
- [README](../../README.md), [current state](../current-state.md), ADRs
  [0001](../adr/0001-modular-monolith.md)/[0002](../adr/0002-feature-modules.md),
  tenancy architecture/runbook and API contracts for
  [inventory](../api/inventory.md), [orders](../api/orders.md), and
  [events](../api/events.md).
- [Testing commands](../testing/README.md), backend regression map and
  [migration procedures](../testing/migrations.md).

Closure/checkmarks and historical inspection revisions do not establish current
acceptance. R1/R2/R8/R9/R13 are assessed within T2's revision/episode producer
scope. Event emission, delivery, projections, notifications and complete
maintenance initialization belong to later issues.

## Acceptance criteria and evidence

AC1-AC5 follow the five GitHub bullets in order. Coverage: **5 Passed, 0 Failed,
0 Untested within T2 scope**. Each pass combines inspection with the fresh
execution evidence below; later consumer/maintenance behavior is excluded.

| ID | Assessment and evidence |
|---|---|
| AC1: monotonic state revisions, restaurant lock, exact low predicate | **Passed — inspection and regression execution.** `inventory/service.py:119` advances revision once for an actual quantity, threshold or active-state change; creation starts at 1. Domain logic uses exactly `active AND quantity <= threshold`. Unit cases cover zero/equality/above-threshold/inactive states. `test_episode_lifecycle_revisions_snapshots_and_noops` verifies monotonic progression, same-value/name-only edits and zero-delta counts; `test_creation_at_zero_with_zero_threshold_opens_episode` checks the zero boundary. Balance version still advances on zero-delta counts while state revision does not. |
| AC2: creation, continued-low, recovery, threshold, archive and restore | **Passed — inspection and regression execution.** Shared writer opens one UUID on entry, retains it during continued-low changes and resolves once with `stock_recovered`, `threshold_changed` or `archived`. The PostgreSQL lifecycle test checks further deductions, threshold changes remaining low, threshold resolution/reopening, archive and restore with a new UUID. Domain tests check archive precedence when threshold changes simultaneously. Literal reason spellings agree with T1 and the local task/API contract; GitHub prose describes the same meanings. |
| AC3: immutable opening snapshots and complete resolution history | **Passed — producer inspection and regression execution.** Episode model retains scope, name/unit, opening quantity/threshold/time/revision/source/actor/order plus complete closing state/time/revision/reason/provenance. Resolution returns both opening and closing facts. Migration trigger rejects opening mutation/deletion and subsequent resolved-row updates; partial unique index permits one open episode per ingredient. Lifecycle test checks rename-independent snapshots and closing facts; `test_opening_facts_are_immutable_and_survive_ingredient_deletion` executes mutation/deletion rejection and verifies retained snapshots after ingredient removal. Actual close-before-open consumer processing is T7, not claimed here. |
| AC4: shared interface, lock order, atomicity and physical-count conflicts | **Passed — inspection and regression execution.** Inventory create/update/change and `orders/service.py:329` use `record_inventory_transition` within service-owned transactions. Orders acquire restaurant then order locks; `orders/repo/queries.py:105` orders ingredient/balance locks by ingredient ID. Repositories do not commit. `test_manual_receipt_waste_and_count_serialize_with_acceptance` checks acceptance opening/receipt resolution revisions, stale-count conflict and insufficient-waste rejection. Competing-manager acceptance tests check one successful consumption/episode. The overlap helper at `test_order_inventory.py:202` coordinates events around the held restaurant lock, rather than sleeps. Flush-failure cases verify order/balance/ledger/audit/revision/episode rollback. |
| AC5: no-op, replay, rollback, cancellation and truthful baseline | **Passed — inspection and regression execution.** State no-ops return `None` before episode writes; stock replays return before mutation. Lifecycle tests assert replay identity and unchanged revision/episode counts. Inventory management tests check mismatched keys and stale counts. Episode/audit injection and acceptance balance/movement/order/audit failures check rollback. Cancellation preserves quantity, revision and the open episode. Baseline helper records observation time, `maintenance_initialization` and suppression without revision bump; its integration test repeats initialization with the same episode/time. Legacy upgrade gives revision 1 without fabricated episodes. |

Primary tests: `backend/tests/unit/test_inventory_transitions.py`,
`backend/tests/integration/test_inventory_episodes.py`,
`backend/tests/integration/test_inventory_management.py` and
`backend/tests/integration/test_order_inventory.py`.

## Findings

No actionable T2 behavior defect was identified. Two documentation findings
remain; they do not represent failed business acceptance criteria.

### F1 — P3: T2 summaries retain superseded unit-verification limitation

Locations: `docs/current-state.md:50`,
`docs/milestone8/milestone-8-task.md:11` and `:131`.

A reader checking T2 readiness still sees full unit validation described as
unverified because of the Windows socket-guard stall. This review's Python
3.12.13 run outside the sandbox passed all 259 tests. The old run is historical
evidence, not the latest conclusion; its stack observation does not establish
a current socket-guard defect. Impact: readers can incorrectly consider T2
blocked on unit validation. Suggested correction: append dated current results,
preserve the historical incomplete run, and retain the distinction between
partial issue checks and full milestone acceptance. Other documents are left
unchanged by this report-only review.

### F2 — P3: event contract describes implemented transitions as future work

Location: `docs/api/events.md:63–65`.

The paragraph says business event emission and inventory transition persistence
land in later M8 tasks. Transition persistence is implemented at reviewed HEAD;
event emission remains T3. Read as a current contract, this can lead later
producers to overlook the shared writer and duplicate revision/episode logic.
Suggested correction: explicitly identify the original T1 scope, link the
implemented inventory interface, and preserve the T3 emission boundary. No API
behavior change is required.

## Executed checks

Environment: Windows, Python 3.12.13 (`backend/.venv-m6-dev`), existing locked
dependencies, disposable PostgreSQL 16 and Redis 7. No installation/resolution.
Commands run from repository root unless stated otherwise.

```powershell
./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe -Gate backend-static,backend-unit,backend-integration,migrations -NoInstall
```

| Check | Result |
|---|---|
| Initial combined command inside sandbox | Environment failure before gates: Docker named-pipe access denied. Approved rerun outside sandbox used only disposable test resources. |
| backend-static | Passed: Ruff lint, format check (185 files), mypy (133 source files). |
| backend-unit | Passed: 259 tests, including 16 inventory transition and 18 event contract cases; one existing Starlette/httpx deprecation warning. |
| backend-integration | Passed: 234 PostgreSQL/Redis tests, including all six episode cases and stock/order regressions; Alembic reported no new upgrade operations. Existing Starlette/httpx and datetime.utcnow deprecation warnings. |
| migrations | Passed: clean and seeded legacy upgrades to unique head, model-drift checks, preservation of legacy business/stock/replay facts, revision-1/no-fabricated-episode baseline, and order/event/episode retained-history downgrade guards. |
| `.venv-m6-dev/Scripts/python.exe -m alembic heads` from `backend/` | Passed: unique repository head `b8f34c2a91de`. |
| `.venv-m6-dev/Scripts/python.exe -m alembic upgrade c61a0f3d9e42:b8f34c2a91de --sql` from `backend/` | Passed: generated/reviewed additive T2 SQL, defaults/checks/indexes/retention trigger. Offline SQL generation did not migrate a database. |

The combined approved command exited 0 with `PASS: partial validation (not
milestone acceptance)`. Owned disposable databases were dropped and Compose
containers/network removed. The earlier incomplete full-unit result is superseded
by this supported-baseline run.

## Schema, interfaces and coverage limits

Migration `b8f34c2a91de` follows `c61a0f3d9e42`, adding non-null revision
(default 1) and durable `inventory_low_stock_episodes`. It preserves balances,
movements/audits and does not fabricate legacy episodes. Scope/source identifiers
lack cascading business-object foreign keys. Downgrade refuses before destructive
DDL when episode rows exist; empty-history downgrade removes table/trigger/column.

Shared internal interfaces are `record_inventory_transition`,
`load_inventory_state(..., lock=True)` and `record_baseline_inventory_episode`.
Returned transition facts are staged in the caller's transaction and become
durable only after commit. This corrects the previous report's shorthand calling
the returned revision committed. HTTP routes/contracts and physical-count
version semantics are preserved. T2 emits no business events.

The baseline helper supplies an ingredient-level suppressed observation path;
it is not the full maintenance operation. Scoped initialization markers/operator
provenance/reruns after resolution belong to T8/#38. Close-before-open delivery,
stale projection/stub handling, worker recovery, receipts/retries, analytics and
freshness remain later tasks and are untested by this review.

Not every database constraint/trigger branch is individually executed by existing
suites: resolved-row mutation rejection and some identity/closing-fact constraints
have inspection evidence. Baseline regression covers an already-open rerun, not
the full maintenance lifecycle. These limits are not completion claims for later
issues.

Application database was not inspected or migrated; its recorded historical
revision is not asserted as current. Full ten-gate validation, locked installation,
final GitHub PR CI and frontend/browser/image gates were omitted. The required
issue command set covers this backend/schema slice; partial checks do not establish
the roadmap's three M8 exit criteria.

## Historical implementation verification

Previous report recorded Python 3.13.15: static passed, 234 integration tests and
clean/seeded migrations passed, focused transition/event modules passed 18 tests,
and full unit gate did not complete in the Windows Proactor socketpair path.
These results describe the earlier execution before the current contract fix
and supported-baseline review; they are retained as history, not used as current
acceptance evidence.
