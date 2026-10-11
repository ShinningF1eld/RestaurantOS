# Milestone 8 Issue #32 verification

Date: 2026-10-11. Scope: T2, capture inventory revisions and low-stock episode
transitions atomically. The application database was not migrated, and no
Issue #33 event emission or later worker/consumer behavior is included.

## Implementation and acceptance evidence

| Issue #32 criterion | Implementation and evidence |
|---|---|
| Monotonic state revisions under the restaurant lock; exact low predicate; retain physical-count version semantics | `inventory_ingredients.state_revision` starts at 1 and advances only for actual balance, threshold, or active-state changes. The pure transition unit cases and PostgreSQL lifecycle test cover the `active AND quantity <= threshold` predicate (including `0 <= 0`), unchanged name/unit and zero-delta counts, and the separate balance version. |
| Episode opening, continuity, recovery, threshold reevaluation, archive, and restore | Shared service logic records one stable UUID while low, resolves it with `stock_recovered`, `threshold_changed`, or `archived`, and creates a new identity after restoration while low. PostgreSQL lifecycle and order-acceptance cases cover these boundaries. The resolution values use the underscores already established by T1, as explicitly selected by the user. |
| Immutable opening facts and durable resolution facts independent of later delivery order | Episode rows retain organization/restaurant/ingredient identity, opening name/unit/quantity/threshold/time/revision/source/actor/order, and the complete resolution snapshot. A database trigger protects opening facts and makes a resolved row immutable; a partial unique index allows at most one open episode per ingredient. Tests cover opening snapshots, resolution facts, and persistence after ingredient deletion. |
| One transition writer for manual stock and order consumption with existing lock order and transaction behavior | `record_inventory_transition` is called within both existing write transactions. Manual writes hold restaurant then ingredient locks; order acceptance holds restaurant, order, then ascending ingredient locks. PostgreSQL tests cover order opening facts, overlap with stock changes, rollback, audit/ledger atomicity, cancellation without restock/resolution, and competing order acceptance. |
| No-op, replay, rollback, cancellation, and baseline behavior | Lifecycle tests cover idempotent replay, unchanged state, same-value edits, failed unit changes, repeated deductions, and suppressed baseline initialization without a revision bump. Injected episode/audit failures verify rollback. Cancellation leaves stock and the open episode unchanged. |

## Database changes

Migration `b8f34c2a91de` adds `inventory_ingredients.state_revision` with a safe
default of 1 and creates `inventory_low_stock_episodes`, its scope/history
indexes, one-open-episode partial unique index, state checks, and the immutable
facts trigger. Historical low ingredients are not assigned fabricated episodes.
Episode scope/source IDs do not cascade with business-object deletion. Downgrade
raises before destructive DDL if retained episode rows exist.

The repository has one Alembic head, `b8f34c2a91de`. The clean and seeded
disposable migration paths passed, including `alembic check`, legacy inventory
preservation, and the retained-episode downgrade guard. The app database remains
at its last recorded revision until a separately authorized maintenance
operation.

## Verification run

| Command | Result |
|---|---|
| `& .\scripts\validate.ps1 -Gate backend-static -NoInstall` | Passed: Ruff lint, Ruff format check, and mypy (133 source files). |
| `& .\scripts\validate.ps1 -Gate backend-integration -NoInstall` | Passed: 234 PostgreSQL/Redis integration tests; migration/model drift check reported no new upgrade operations. |
| `& .\scripts\validate.ps1 -Gate migrations -NoInstall` | Passed: clean and seeded upgrades, unique head, model drift, legacy preservation, and prohibited order/event/episode downgrade checks. |
| `backend/.venv/Scripts/python.exe -m pytest tests/unit/test_inventory_transitions.py tests/unit/test_event_contracts.py -q` (from `backend/`) | Passed: 18 tests. |
| `& .\scripts\validate.ps1 -Gate backend-unit -NoInstall` | Attempted but did not complete: the pre-existing unit-only socket guard stalled in the first asynchronous auth test at Python's Windows Proactor `socketpair()` path. No full backend-unit pass is claimed. |

The service-backed gates used disposable databases/containers and removed their
owned resources. The host interpreter reported Python 3.13.15 (the repository's
supported baseline is Python 3.12); the launcher also printed a missing
Python313 installation-path warning while executing successfully. The full
ten-gate validation was not run; these are partial gate runs, not Milestone 8
acceptance evidence. No frontend gate applies to this backend-only slice.

## Issue #33 readiness

`record_inventory_transition` returns an immutable `InventoryTransition` with
the committed state revision, current episode ID, boundary transition, and
complete episode facts. `load_inventory_state(..., lock=True)` provides a
trusted locked state read; `record_baseline_inventory_episode` supplies the
observation-time, notification-suppressed maintenance path. These interfaces
are ready for Issue #33. This issue does not emit business events.
