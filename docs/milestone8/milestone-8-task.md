# Milestone 8 task plan

Status: Published
Source: docs/milestone8/milestone-8-design.md, approved revision 1 (2026-10-11); RestaurantOS_Master_Roadmap.md, Milestone 8.
Inspected revision: 156badacb0dba913d3548389cb1c08d34316539b; working tree initially clean.
Updated: 2026-10-11 (Asia/Bangkok)
Target: ShinningF1eld/RestaurantOS
GitHub milestone: [Milestone 8 Reliable background jobs and domain events](https://github.com/ShinningF1eld/RestaurantOS/milestone/3) (GitHub milestone number 3; product milestone 8).
Publication authorization: user requested creation of milestone-8-task.md and GitHub issues with acceptance criteria, all assigned to GitHub Milestone 8.
Task-plan revision: 1. All criteria below are planned and unverified.

## Ordered tasks

| ID | Outcome | Requirements | Depends on | Publication |
|---|---|---|---|---|
| T1 | Define event contracts and durable delivery storage | R1, R3–R5, R11, R13 | None | [#31](https://github.com/ShinningF1eld/RestaurantOS/issues/31) |
| T2 | Capture inventory revisions and low-stock episode transitions atomically | R1, R2, R8, R9, R13 | T1 | [#32](https://github.com/ShinningF1eld/RestaurantOS/issues/32) |
| T3 | Emit committed order, catalog and inventory events within business transactions | R1, R2, R3, R11 | T1, T2 | [#33](https://github.com/ShinningF1eld/RestaurantOS/issues/33) |
| T4 | Run Redis Streams relay and PostgreSQL recovery in a separate worker | R3, R4, R5, R11, R13 | T1 | [#34](https://github.com/ShinningF1eld/RestaurantOS/issues/34) |
| T5 | Commit consumer receipts and bounded retries with safe inspection and replay | R4, R5, R6, R11 | T4 | [#35](https://github.com/ShinningF1eld/RestaurantOS/issues/35) |
| T6 | Project completed daily sales with revision tombstones and reconciliation | R4, R7, R13 | T3, T5 | [#36](https://github.com/ShinningF1eld/RestaurantOS/issues/36) |
| T7 | Project alert history and deduplicated notification and diagnostic records | R4, R8, R9, R13 | T3, T5 | [#37](https://github.com/ShinningF1eld/RestaurantOS/issues/37) |
| T8 | Initialize and rebuild derived state safely during maintenance | R6, R7, R8, R9, R11, R13 | T6, T7 | [#38](https://github.com/ShinningF1eld/RestaurantOS/issues/38) |
| T9 | Expose scoped inventory alerts and history with resilient refresh | R10, R12 | T7, T8 | [#39](https://github.com/ShinningF1eld/RestaurantOS/issues/39) |
| T10 | Enforce worker failure and workflow regressions in shared validation gates | R1–R14 | T6, T7, T8, T9 | [#40](https://github.com/ShinningF1eld/RestaurantOS/issues/40) |
| T11 | Measure processing freshness and publish Milestone 8 operational evidence | R3, R6, R11–R14; roadmap exit criteria | T10 | [#41](https://github.com/ShinningF1eld/RestaurantOS/issues/41) |

## Coverage and sequencing

T1 establishes shared contracts and durable storage. T2 and T4 can proceed independently after T1; T3 follows T2 and T5 follows T4. Analytics T6 and alerts/sink T7 can proceed independently once producers and delivery execution exist. T8 integrates maintenance initialization/rebuild; T9 completes alert API/UI; T10 verifies full workflows and gates; T11 records measured freshness and acceptance evidence. Each slice includes its own critical regressions rather than deferring correctness to T10.

| Requirement | Primary implementation/evidence tasks |
|---|---|
| R1 Atomic committed events | T1, T2, T3, T10 |
| R2 Business invariants | T2, T3, T10 |
| R3 Recover unfinished delivery | T3, T4, T10, T11 |
| R4 Duplicate-safe effects | T1, T4, T5, T6, T7, T10 |
| R5 Failure isolation/bounded retries | T4, T5, T10 |
| R6 Safe operator recovery | T5, T8, T10, T11 |
| R7 Correct analytics | T6, T8, T10 |
| R8 Low-stock episodes/history | T2, T7, T8, T10 |
| R9 Durable stubs/diagnostics | T7, T8, T10 |
| R10 Scoped alert reads/history | T9, T10 |
| R11 Correlation/inspectability | T1, T3, T4, T5, T8, T11 |
| R12 Honest freshness/UI cadence | T9, T11 |
| R13 Safe initialization/retention | T1, T2, T4, T6, T7, T8, T10, T11 |
| R14 Validation/documentation | Every slice; T10, T11 |

Scope follows approved revision 1: PostgreSQL outbox is authoritative, Redis Streams is recoverable transport, and three independent consumer responsibilities run within one separate worker program. Added order.deleted.v1 and inventory.state_changed.v1 and broader menu operations are accepted design refinements to the roadmap. Dashboard SQL stays live; external messaging, repeated reminders, alert acknowledgement/dismissal, forecasts, M9 deployment, M10 full tracing and M11 broader metric/timezone modeling remain deferred.

Inspection confirms service-owned transactions in orders/inventory/catalog and live completed analytics grouped by order creation date. No events/worker module or durable alert projection exists. Inventory low_stock is a live quantity/threshold check; new state revisions must preserve existing balance-version count conflicts. Catalog currently has post-commit invalidation that producer integration must retain.

Documentation disagreements remain explicitly disclosed by the design: older roadmap status labels and root PostgreSQL rate-limit wording differ from dated implementation evidence/current Redis admission behavior. GitHub currently shows all nine M7 issues closed; this alone does not replace dated final-CI evidence or authorize unrelated documentation/runtime changes. This plan does not implement M8 or mark its criteria complete.

Likely affected implementation locations: backend/app/modules/{events,orders,catalog,inventory,analytics,alerts,notifications}/; shared backend worker/Redis adapters, core settings/logging, backend/alembic/versions/ and metadata registration; frontend inventory route/features, types and lib/api; scripts/test_support, scripts/validate.py, tests, backend/Dockerfile if extended; docs/api/, docs/architecture/, docs/runbooks/, docs/testing/, README/current-state and M8 evidence.

Schema risks: additive event/delivery/receipt/attempt/replay, revision/transition, projection, episode, sink and initialization data need safe populated defaults, scoped constraints/indexes and one migration head. No cascade may erase facts when business objects disappear; downgrade must reject destructive history loss. Test clean/seeded legacy upgrades and alembic check in disposable databases only. Application cutover remains an explicit backed-up maintenance operation; neither this planning task nor validation migrates the application database.

Exact filenames/table names, API subpaths/page sizes, CLI flags and conservative runtime budgets are implementation choices to record in the owning slice before coding/acceptance. They must preserve agreed semantics; material scope changes require an accepted design revision. No commit, push, PR, application migration or implementation is authorized by this planning/publication request.

## Complete issue bodies

### T1: Define event contracts and durable delivery storage

## Purpose and references

Define event contracts and durable delivery storage. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R1, R3–R5, R11, R13.

## Scope

Add a cohesive events module (service.py, domain/, repo/), typed envelopes/subscription registry, and additive Alembic schema in backend/alembic/versions/. Register models in shared metadata. Define producer order revisions and inventory transition interfaces needed by subsequent slices; consumer-owned tables land with their consumers.

## Dependencies

None.

## Acceptance criteria

- [ ] Define all eight approved contracts: order.submitted.v1, order.accepted.v1, order.completed.v1, order.cancelled.v1, order.deleted.v1, menu.updated.v1, inventory.state_changed.v1, inventory.low.v1. Record typed fields, trigger/no-op matrix, and the fixed event-to-consumer subscription matrix in docs/api/.
- [ ] Envelopes carry stable UUID, consistent type/version, verified organization/restaurant, aggregate identity/revision, UTC occurrence time and request correlation. Serialize decimal money/quantities losslessly; explicitly interpret naive order creation timestamps as UTC while retaining creation-date grouping. Exclude customer names/notes, credentials, cookies, headers and arbitrary request bodies.
- [ ] Persist immutable events, per-consumer delivery state, unique (consumer,event_id) receipts, retained attempt/replay history and claim ownership. Required delivery rows are inserted alongside the event through a public service interface using the caller's transaction; repositories never commit.
- [ ] Constraints enforce applicable scope/identity relationships; deleting orders/menu items/ingredients cannot cascade-delete durable event or history facts. Redis metadata cannot select handlers or override authoritative payloads.
- [ ] Add order revision metadata with safe populated-database defaults; preserve immutable snapshots and existing history. Review migration SQL/indexes and downgrade guards against discarding retained work; maintain one Alembic head and no implicit startup migration.

## Verification

Run backend-unit, backend-integration, backend-static and migrations. Test serialization/version rejection, subscription fan-out atomicity, uniqueness/scope constraints, clean/seeded upgrades and retained-data downgrade guards.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T1 -->

### T2: Capture inventory revisions and low-stock episode transitions atomically

## Purpose and references

Capture inventory revisions and low-stock episode transitions atomically. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R1, R2, R8, R9, R13.

## Scope

Extend inventory domain/service/repository and expose a public transition/state interface for orders and alerts. Add additive inventory revision and durable episode transition metadata migrations. Preserve the balance-version physical-count contract.

## Dependencies

[T1](https://github.com/ShinningF1eld/RestaurantOS/issues/31).

## Acceptance criteria

- [ ] Under the existing restaurant lock, assign monotonic state revisions for actual balance, threshold and active-state changes and persist stable episode IDs plus opening/closing facts. State is low exactly when active and quantity <= reorder_threshold, including zero at a zero threshold.
- [ ] Creation with low opening stock opens one episode; further changes while low do not open another. Recovery above threshold, threshold reevaluation and archive resolve with explicit stock-recovery/threshold-change/archive reasons. Restoration while low opens a new episode.
- [ ] Capture immutable ingredient name/unit, opening quantity/threshold, timestamps and resolution facts sufficient for history even when close events arrive first. Producer facts, not worker arrival order, determine episode identity.
- [ ] Manual stock changes and order consumption use the same public inventory transition interface and retain restaurant/order/ascending ingredient locks, ledger/balance/audit atomicity and unchanged physical-count conflicts.
- [ ] No-op updates, stock command idempotent replays and rollback do not advance state or emit transitions; cancellation neither restores stock nor resolves an episode. Baseline initialization has a supported suppression/provenance path rather than invented historical transitions.

## Verification

Run backend-unit, backend-integration, backend-static and migrations. Cover every transition boundary and threshold/archive/restore case, idempotency conflicts and deterministic overlapping stock/acceptance writes.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T2 -->

### T3: Emit committed order, catalog and inventory events within business transactions

## Purpose and references

Emit committed order, catalog and inventory events within business transactions. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R1, R2, R3, R11.

## Scope

Integrate events' public append interface into backend/app/modules/orders/service.py, catalog/service.py and inventory/service.py using their existing write transactions. Keep business routes and post-commit catalog invalidation intact.

## Dependencies

[T1](https://github.com/ShinningF1eld/RestaurantOS/issues/31), [T2](https://github.com/ShinningF1eld/RestaurantOS/issues/32).

## Acceptance criteria

- [ ] Emit order lifecycle events only on genuine approved transitions; completion snapshots include authoritative total, creation timestamp and revision. Permitted deletion captures sufficient identity/revision facts before removal for analytics tombstones.
- [ ] Emit menu.updated.v1 for actual menu/item creation, edit, deactivation and deletion with operation/affected identities; inventory.state_changed.v1 for actual resulting state changes and inventory.low.v1 only for new episodes. Multiple events in one command share correlation.
- [ ] Business state, stock ledger, audit facts, immutable event and required consumer deliveries commit together. Inject audit/event/delivery/flush failures and prove complete rollback, including no partially visible fan-out.
- [ ] Read requests, unchanged status/no-op edits and command retries emit no duplicate business event. Preserve authorization locks, current membership/assignment checks, monetary snapshots, idempotency replay/mismatch and cancellation without restock.
- [ ] An API process killed after commit and before any transport publication leaves all events/deliveries recoverable by a later worker; API writes require neither Redis nor a running worker. Existing post-commit cache invalidation and API Redis/auth failure policies remain unchanged.

## Verification

Run backend-unit, backend-integration and backend-static. Use real PostgreSQL rollback injection and a controlled actual API-process crash boundary; inspect committed records rather than relying on logs.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T3 -->

### T4: Run Redis Streams relay and PostgreSQL recovery in a separate worker

## Purpose and references

Run Redis Streams relay and PostgreSQL recovery in a separate worker. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R3, R4, R5, R11, R13.

## Scope

Add the backend worker entrypoint and shared transport adapters, dedicated bounded Redis pool/configuration, relay/recovery loops and three independent consumer groups on one namespaced stream. Integrate isolated worker runtime support without introducing a deployment platform.

## Dependencies

[T1](https://github.com/ShinningF1eld/RestaurantOS/issues/31).

## Acceptance criteria

- [ ] Use Redis 7-compatible commands and minimal messages containing stable event UUID/routing metadata; load typed facts from PostgreSQL. Independently grouped analytics, alerts and sink consumers acknowledge non-subscriptions without effects.
- [ ] Claim due work in short SKIP LOCKED-style database transactions with expiring leases/ownership fencing. Select and document conservative batch, concurrency, claim, scan/republication, network/read and shutdown budgets; never hold business locks during Redis/network I/O.
- [ ] Publication observation is not completion. Scan only unfinished subscribed deliveries with bounded rate/leases; recreate lost streams/groups, reclaim abandoned pending messages and republish after stall or Redis restart/content loss using the original UUID.
- [ ] Ambiguous publication/acknowledgement, relay crash and old-claim completion cannot lose work or overwrite a newer claim; persisted next-attempt times remain authoritative against early stream redelivery and recovery does not flood messages.
- [ ] API and worker startup do not migrate or start one another. Worker shutdown stops claims with bounded grace; forced termination remains recoverable. Its pool/read budgets do not compete with or change API cache/auth policies, and local Redis persistence stays disabled.
- [ ] Report stream size and retained PostgreSQL work; introduce no automatic event/receipt/history deletion or stream trimming.

## Verification

Run backend-unit, backend-integration, backend-static and image if the runtime image is extended. Exercise real worker/Redis processes, ambiguous publish, pending reclaim, two relay workers, expired claims, restart/content loss and graceful/forced shutdown.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T4 -->

### T5: Commit consumer receipts and bounded retries with safe inspection and replay

## Purpose and references

Commit consumer receipts and bounded retries with safe inspection and replay. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R4, R5, R6, R11.

## Scope

Implement fixed-registry consumer execution, delivery/attempt orchestration and trusted-operator CLI status/inspect/replay. Consumer services own effect transactions; transport adapters acknowledge only afterward.

## Dependencies

[T4](https://github.com/ShinningF1eld/RestaurantOS/issues/34).

## Acceptance criteria

- [ ] Commit each consumer's effect, unique receipt and successful delivery state in one transaction, then ACK Redis. Serialize overlapping attempts with constraints/locks; an initial receipt lookup alone cannot provide safety. Deliberate skip outcomes receive durable receipts.
- [ ] One failed consumer never reruns successful effects in another. A crash before effect commit retries cleanly; a crash after commit/before ACK is receipt-checked and produces one effect. Reject missing/conflicting event references without trusting Redis facts.
- [ ] Event-specific transient failures get eight total attempts by default, persisted exponential backoff starting at one second and capped at 60 seconds with documented small bounded jitter. Unsupported versions/invalid payloads fail immediately and remain inspectable.
- [ ] Classify shared PostgreSQL/Redis/dependency outages separately: pause affected loops with bounded backoff/probes without exhausting unrelated event allowances. Event-caused database constraints must not suspend all work indefinitely. Persist history and respect due times after restart.
- [ ] CLI status exposes per-consumer pending depth, oldest age, retries, failed/retained counts and stream size; inspect shows safe identity/scope/version/attempt/error facts. Use trusted operator credentials rather than treating a free-form actor label as access authority.
- [ ] Replay targets exactly one failed delivery, retains its original event/payload and prior attempts/receipts, records reason/time/operator provenance/replay-operation identity and starts a new retry cycle. Reject invalid or already successful replay targets.
- [ ] Propagate original request correlation through relay/attempts/replay with event/consumer/attempt context; deliberately extend logging allowlists and redact secrets, customer payloads, Redis URLs and raw driver exceptions.

## Verification

Run backend-unit, backend-integration and backend-static. Use deterministic clocks for retry policy, barriers for duplicate overlap, actual worker crashes, independent-group poison/outage cases and CLI replay provenance/redaction checks.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T5 -->

### T6: Project completed daily sales with revision tombstones and reconciliation

## Purpose and references

Project completed daily sales with revision tombstones and reconciliation. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R4, R7, R13.

## Scope

Implement analytics-owned contribution/tombstone and daily aggregate persistence with additive migrations, consumer service and operator inspection/reconciliation. Keep the dashboard and existing analytics routes on live SQL.

## Dependencies

[T3](https://github.com/ShinningF1eld/RestaurantOS/issues/33), [T5](https://github.com/ShinningF1eld/RestaurantOS/issues/35).

## Acceptance criteria

- [ ] Apply order.completed.v1 to per-order contribution/revision state and daily completed count/sales by restaurant and order creation date, matching current authoritative SQL and fixed precision; do not switch to completion date or restaurant timezone.
- [ ] Apply permitted deletion by removing the contribution and retaining a revision tombstone; older/duplicate completion cannot resurrect it. Out-of-order completion/deletion and replay yield the same result as current SQL.
- [ ] Receipt, contribution/tombstone and aggregate delta commit atomically. Overlapping different orders updating one day do not lose increments; duplicate same-order attempts yield one contribution.
- [ ] Provide inspectable projection output and scoped authoritative-SQL reconciliation identifying discrepancies; dashboard reads remain live SQL. Item/category/timezone/refund metrics remain M11.
- [ ] Expose a maintenance seeding/rebuild interface with order revision watermarks usable by T8; receipts remain truthful and queued old events cannot double count or undo a rebuilt baseline. Add model registration, single-head migration and retained-data downgrade protections.

## Verification

Run backend-unit, backend-integration, backend-static and migrations. Compare SQL/projection across multiple restaurants, decimal totals, completion/deletion permutations, lock-proven same-day concurrency and baseline plus queued events.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T6 -->

### T7: Project alert history and deduplicated notification and diagnostic records

## Purpose and references

Project alert history and deduplicated notification and diagnostic records. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R4, R8, R9, R13.

## Scope

Add alerts-owned episode projection/current revision state and an actual notification/diagnostic sink module with additive migrations. Use inventory's public authoritative state/lock interface; expose read/init hooks for T8/T9.

## Dependencies

[T3](https://github.com/ShinningF1eld/RestaurantOS/issues/33), [T5](https://github.com/ShinningF1eld/RestaurantOS/issues/35).

## Acceptance criteria

- [ ] Project opening/resolution history from producer episode facts, preserving immutable name/unit/opening quantity/threshold and provenance even across rename/archive and close-before-open delivery.
- [ ] Per-ingredient revisions prevent older state from replacing newer current state. Delayed historical opening may fill history but cannot reopen a resolved or superseded episode; repeated low deductions create neither another episode nor a reminder.
- [ ] Under the same restaurant lock as stock writes, check current active/low state and episode identity before committing at most one low-stock stub per episode through a unique episode key. Commit outcome and receipt atomically without external I/O under the lock.
- [ ] Persist skip outcomes/receipts for resolved or superseded episodes; initialization baselines suppress notifications. Resolution before stub commit skips it, while replenishment after stub commit preserves the historical stub and resolves the alert.
- [ ] Order lifecycle/deletion and menu events produce durable deduplicated operator diagnostic records; logs alone are not the effect. There is no external delivery, repeated reminder, acknowledge or dismiss behavior.
- [ ] Derived rebuild preserves historical snapshots/receipts and baseline provenance; producer transition facts remain available for reconstruction. Register tables, preserve business-deletion references and protect retained history on downgrade.

## Verification

Run backend-unit, backend-integration, backend-static and migrations. Prove out-of-order history/current-state behavior, baseline suppression, unique stubs and both stock-versus-stub lock boundaries using explicit coordination.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T7 -->

### T8: Initialize and rebuild derived state safely during maintenance

## Purpose and references

Initialize and rebuild derived state safely during maintenance. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R6, R7, R8, R9, R11, R13.

## Scope

Implement trusted-operator maintenance initialization and analytics rebuild/reconcile commands plus scoped initialization markers/provenance. Write executable backup/cutover/rebuild runbooks; validate only against disposable databases.

## Dependencies

[T6](https://github.com/ShinningF1eld/RestaurantOS/issues/36), [T7](https://github.com/ShinningF1eld/RestaurantOS/issues/37).

## Acceptance criteria

- [ ] Document and exercise the explicit sequence: pause/quiesce business writes and stop workers, inspect actual application revision/backup, explicitly migrate, seed analytics/revision watermarks, baseline active-low episodes, persist notification suppression, then start workers/resume writes.
- [ ] Initialize from existing completed orders without historical lifecycle events; queued completion/deletion cannot double count or undo watermarks. Preserve all pending events and successful receipts.
- [ ] Create 'low at initialization' episodes using observation time and immutable current opening facts, not fabricated start times. Persist scoped markers/provenance so reruns do not duplicate baselines or recreate resolved ones.
- [ ] Already-low baselines remain notification-suppressed until recovery and a genuinely new episode. Verify reruns with later stock/threshold/archive changes and existing event history.
- [ ] Analytics rebuild is maintenance reconstruction, not receipt deletion/replay. Preserve alert history, event/attempt/replay/receipt/stub records; reconciliation proves correct totals afterward and reports retained counts/storage-growth limitations.
- [ ] Record executable CLI names/flags, trusted operator access, safe output, preconditions, interruption/rerun recovery and backup procedures. No validation script migrates the application database or removes the developer volume; live cutover requires its separate explicit operation.

## Verification

Run backend-integration, backend-static and migrations against seeded legacy/new disposable state. Exercise interrupted initialization, scoped reruns, resolved baseline rerun, pending older events and rebuild with retained successful receipts.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T8 -->

### T9: Expose scoped inventory alerts and history with resilient refresh

## Purpose and references

Expose scoped inventory alerts and history with resilient refresh. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R10, R12.

## Scope

Add paginated alert/history reads under the existing restaurant inventory namespace and integrate the existing frontend inventory page/InventoryManager, feature UI, types and shared API helpers. Settle exact subpaths/types/page size and document the contract before coding this slice.

## Dependencies

[T7](https://github.com/ShinningF1eld/RestaurantOS/issues/37), [T8](https://github.com/ShinningF1eld/RestaurantOS/issues/38).

## Acceptance criteria

- [ ] Resolve current membership/capability/branch assignment on every direct/nested/list/count/history read using inventory.read: Owners cover their organization, Managers require assignment, Employees cannot read alerts. Foreign/unassigned resources return 404 and forbidden capabilities 403; revocation immediately removes access.
- [ ] Active alerts present authoritative current quantity/base unit/threshold with episode start; paginated history presents immutable opening facts/start/resolution/baseline provenance/reason. Pagination and counts cannot leak another tenant/branch.
- [ ] Place active alerts above ingredients and a collapsible paginated Alert history section on the existing inventory page; retain live low_stock indicators while workers catch up, and add no acknowledge/dismiss controls.
- [ ] Refresh every 15 seconds only while visible, after local stock actions, and on manual request. Preserve entered form values/editor focus and prevent stale overlapping requests from replacing newer results.
- [ ] Distinguish loading/error/stale/empty states; retain clearly marked last-known data on failure with retry, never present a failed request as 'no alerts'. Handle access revocation and restaurant changes without showing prior scoped data.
- [ ] Before frontend code consult installed Next.js docs per frontend/AGENTS.md. Reuse browser/server transports and current URLs, cookie/CSRF/serialized bounded renewal behavior; SSR does not rotate cookies.

## Verification

Run backend-unit/backend-integration/backend-static, frontend-tests/frontend-static/frontend-build and browser. Cover Owner/assigned-unassigned Manager/Employee/cross-tenant/revoked reads, history pagination, visible timer behavior, local action refresh, error retry and form preservation.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T9 -->

### T10: Enforce worker failure and workflow regressions in shared validation gates

## Purpose and references

Enforce worker failure and workflow regressions in shared validation gates. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R1–R14.

## Scope

Integrate missing cross-feature/process/browser regression coverage into scripts/validate.py, scripts/test_support, backend/frontend tests, migration harness, image smoke and existing CI gates. Reuse slice regressions and update testing maps.

## Dependencies

[T6](https://github.com/ShinningF1eld/RestaurantOS/issues/36), [T7](https://github.com/ShinningF1eld/RestaurantOS/issues/37), [T8](https://github.com/ShinningF1eld/RestaurantOS/issues/38), [T9](https://github.com/ShinningF1eld/RestaurantOS/issues/39).

## Acceptance criteria

- [ ] Actual API/worker process cases cover commit-before-publication death, consumer death before commit/after commit-before-ACK, ambiguous publish/ACK, pending reclaim and Redis restart/content loss; every committed subscribed fact reaches one consumer outcome.
- [ ] Prove independent-consumer poison isolation, eight attempts/durable backoff across restart, infrastructure outage recovery without allowance exhaustion, unsupported version failure, safe replay and expired claim fencing. Concurrency tests demonstrate overlap at locks/barriers, not sleeps.
- [ ] Cover transaction/audit/event rollback, no-op/idempotent producers, analytics tombstones/rebuild/daily-row overlap, alert close-before-open/new-episode history and replenishment/stub timing, baseline suppression/rerun, scoped/revoked alert reads and browser refresh/error/form behavior.
- [ ] Existing required gates include worker suites rather than an optional extra command. Keep guarded _test databases, isolated Compose namespaces/random ports and production browser source copies; cleanup owns only test resources and succeeds on injected failures. Auth traces remain disabled.
- [ ] Clean/seeded legacy upgrade and alembic check preserve old untracked menus/unprocessed orders and stock/replay history plus new M8 downgrade guards. Extend worker entrypoint image smoke when the backend runtime image is changed; startup never migrates.
- [ ] Full ./scripts/validate.ps1 with locked installs passes on Python 3.12/Node 24 and final complete PR CI passes all ten shared gates under unchanged Milestone 6 acceptance enforcement. Record commands/revisions/outcomes/omissions; partial or historical runs cannot mark M8 accepted.

## Verification

Run all ten gates via ./scripts/validate.ps1 and final PR CI; exercise service/worker/browser cleanup failure injection and required-check completeness. Preserve dated failure artifacts without sensitive auth data.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T10 -->

### T11: Measure processing freshness and publish Milestone 8 operational evidence

## Purpose and references

Measure processing freshness and publish Milestone 8 operational evidence. Source: `docs/milestone8/milestone-8-design.md`, approved revision 1, 2026-10-11; `RestaurantOS_Master_Roadmap.md`, Milestone 8. Inspected HEAD: `156badacb0dba913d3548389cb1c08d34316539b`. Requirements: R3, R6, R11–R14; roadmap exit criteria.

## Scope

Add a reproducible healthy-load commit-to-effect workload and retained report, operator failure/replay/backlog/Redis-loss runbooks, docs/api event/alert contracts, README/current-state/architecture/testing and roadmap evidence within M8 scope.

## Dependencies

[T10](https://github.com/ShinningF1eld/RestaurantOS/issues/40).

## Acceptance criteria

- [ ] Record dataset/event mix, load/concurrency, environment/tool versions, worker tuning and code revision; measure commit-to-completion P50/P95/P99 and misses against the five-second healthy target for subscribed consumers with a documented reproducible command.
- [ ] Report real target misses/regressions and consumer-specific outcomes, backlog depth/oldest age, retries/failures, retained database counts and Redis stream size. Distinguish worker latency from the UI's 15-second visible refresh cadence; claim no outage-time guarantee.
- [ ] Demonstrate status/inspect/replay after repair, graceful/forced shutdown, Redis content loss/recovery and reconcile/rebuild/initialization using executable commands and safe correlated facts; document original/replay identities and per-consumer recovery.
- [ ] Document selected settings/CLI/API contracts, deployment boundary, maintenance write pause/backup, nonpersistent recoverable Redis, baseline suppression and storage-growth/no-pruning limitations. Dashboard stays on live SQL; external notifications/M9 deployment/M10 tracing/M11 broader analytics remain deferred.
- [ ] Map all R1–R14 and the three roadmap exit criteria to dated passing evidence: no silently lost committed events in tested failures, duplicate-safe analytics/notifications and safe inspect/replay. Include final local full gates and complete final PR CI evidence before marking M8 complete.
- [ ] Keep application database actual revision/cutover evidence distinct from repository migration head; accurately report omissions and unresolved risks. Correct M8-scoped documentation without claiming unrelated stale roadmap/current-state evidence verified.

## Verification

Re-run the documented measurement and operator procedures on isolated services; review retained output against all requirements and roadmap exit criteria, final CI and README claims.

<!-- github-plan: docs/milestone8/milestone-8-design.md | T11 -->

## Publication record

- T1: created [#31](https://github.com/ShinningF1eld/RestaurantOS/issues/31) on 2026-10-11 in GitHub milestone 3 (Milestone 8).
- T2: created [#32](https://github.com/ShinningF1eld/RestaurantOS/issues/32) on 2026-10-11 in GitHub milestone 3 (Milestone 8).
- T3: created [#33](https://github.com/ShinningF1eld/RestaurantOS/issues/33) on 2026-10-11 in GitHub milestone 3 (Milestone 8).
- T4: created [#34](https://github.com/ShinningF1eld/RestaurantOS/issues/34) on 2026-10-11 in GitHub milestone 3 (Milestone 8).
- T5: created [#35](https://github.com/ShinningF1eld/RestaurantOS/issues/35) on 2026-10-11 in GitHub milestone 3 (Milestone 8).
- T6: created [#36](https://github.com/ShinningF1eld/RestaurantOS/issues/36) on 2026-10-11 in GitHub milestone 3 (Milestone 8).
- T7: created [#37](https://github.com/ShinningF1eld/RestaurantOS/issues/37) on 2026-10-11 in GitHub milestone 3 (Milestone 8).
- T8: created [#38](https://github.com/ShinningF1eld/RestaurantOS/issues/38) on 2026-10-11 in GitHub milestone 3 (Milestone 8).
- T9: created [#39](https://github.com/ShinningF1eld/RestaurantOS/issues/39) on 2026-10-11 in GitHub milestone 3 (Milestone 8).
- T10: created [#40](https://github.com/ShinningF1eld/RestaurantOS/issues/40) on 2026-10-11 in GitHub milestone 3 (Milestone 8).
- T11: created [#41](https://github.com/ShinningF1eld/RestaurantOS/issues/41) on 2026-10-11 in GitHub milestone 3 (Milestone 8).

All eleven issue bodies retain the stable design/task identity marker. No assignees, labels, due date, issue closures or application changes were added by this request.
