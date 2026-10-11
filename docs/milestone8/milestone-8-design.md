# Milestone 8: Reliable background jobs and domain events

Status: Approved, revision 1

Updated and inspected: 2026-10-11 (Asia/Bangkok)

Inspection baseline: repository HEAD `9e9cbb3`; working tree clean before document creation.

Approval: the user explicitly accepted the final event/consumer arrangement on
2026-10-11: "I accept. Planning is settle then." The subsequent instruction
authorized writing this document and committing it. Approval applies to this
design; implementation and runtime verification have not been performed.

## Goal and scope

Decouple non-critical processing without silently losing committed events or
duplicating consumer effects. Use a PostgreSQL transactional outbox, Redis
Streams delivery, and a separate backend worker process within the existing
modular monolith.

Deliver three consumer responsibilities: a daily completed-sales/order-count
projection, low-stock alert episodes, and a durable notification/diagnostic sink.
Add active alerts and episode history to the existing inventory page. Provide
operator CLI inspection, replay, initialization, rebuild, and reconciliation.

Order authorization, acceptance, stock consumption, ledger writes, and audit
facts remain synchronous and atomic. Worker or Redis outages may delay derived
work but cannot change business validity. The dashboard continues using live SQL.

This document records agreed future behavior, not completed roadmap criteria.
No implementation, migration, tests, application cutover, or external delivery
is established by this document's approval.

## Sources and current behavior

- [Master roadmap: M8](../../RestaurantOS_Master_Roadmap.md#milestone-8--reliable-background-jobs-and-domain-events)
  specifies outbox atomicity, at-least-once delivery, receipts, bounded retries,
  failure inspection/replay, correlation, and crash/duplicate/version tests.
- [M11](../../RestaurantOS_Master_Roadmap.md#milestone-11--analytics-data-model)
  owns broader metric definitions and restaurant timezone semantics.
- [Current state](../current-state.md), [README](../../README.md),
  [ADR 0001](../adr/0001-modular-monolith.md), and
  [ADR 0002](../adr/0002-feature-modules.md) establish the stack and boundaries.
- [Orders](../api/orders.md), [inventory](../api/inventory.md), and
  [tenancy](../api/tenancy.md) establish transaction, retry, and access contracts.
- [Redis architecture](../architecture/redis.md) and
  [developer Compose](../../docker-compose.yml) establish Redis 7, independent
  use-case failure policies, and deliberately disabled Redis persistence.
- [Testing strategy](../testing/README.md) and
  [migration discipline](../testing/migrations.md) define validation requirements.
- Inspected code: [order service](../../backend/app/modules/orders/service.py),
  [order policies](../../backend/app/modules/orders/domain/policies.py),
  [order models](../../backend/app/modules/orders/repo/models.py),
  [inventory service](../../backend/app/modules/inventory/service.py),
  [analytics queries](../../backend/app/modules/analytics/repo/queries.py),
  [analytics service](../../backend/app/modules/analytics/service.py),
  [tenancy policies](../../backend/app/modules/tenancy/domain/policies.py),
  [logging](../../backend/app/core/logging.py),
  [inventory page](../../frontend/app/restaurants/[restaurant_id]/inventory/page.tsx),
  and [inventory manager](../../frontend/features/inventory/InventoryManager.tsx).

At inspection, there is no outbox or worker implementation. Analytics sums
currently COMPLETED orders by order creation date, not completion date. Orders
without inventory history may be deleted, removing their live SQL contribution.
Inventory already exposes a live `low_stock` flag for active ingredients with
quantity less than or equal to their threshold. Its existing balance version
does not cover every threshold/active-state edit. Structured request correlation
exists; distributed tracing is not established.

Documentation discrepancies: the roadmap tracking table still labels M6
unverified and M7 not started/verify. Dated current-state evidence records M6
acceptance and substantial M7 implementation, with final M7 PR verification
pending. Root engineering instructions also contain an older PostgreSQL-backed
rate-limit statement; current README/code describe Redis admission and a
process-local outage policy. M8 does not alter authentication policy or claim
pending M7 verification complete. These discrepancies were not silently used
as authorization to change unrelated documents or runtime behavior.

## Requirements and acceptance criteria

| ID | Requirement | Observable acceptance criteria |
|---|---|---|
| R1 | Record committed business events atomically | Business write, audit, outbox event, and required consumer delivery records commit together; injected event/audit failures roll everything back. |
| R2 | Preserve business invariants | Acceptance still consumes stock in the request transaction; cancellation never restores it; existing permission, lock, money, and idempotency regressions pass. |
| R3 | Recover unfinished delivery | API crash after commit, relay ambiguity, worker crash, and Redis content loss leave work recoverable from PostgreSQL without another business command. |
| R4 | Prevent duplicate database effects | Each consumer's effect and unique receipt commit together; overlapping deliveries and crash after commit/before acknowledgement produce one effect. |
| R5 | Isolate failures and bound retries | Consumer failure does not rerun successful consumers; event-specific failures have eight attempts with persisted backoff; infrastructure outages do not exhaust all event allowances. |
| R6 | Support safe operator recovery | CLI reports backlog/age/retries/failures, inspects safe failure facts, and replays one failed delivery using its original event identity; replay action and reason are recorded. |
| R7 | Maintain correct analytics | Daily completed count/sales matches authoritative SQL after initialization, duplicates, out-of-order completion/deletion, replay, and rebuild. Dashboard remains on live SQL. |
| R8 | Maintain low-stock episodes | One episode opens on entry into low stock, resolves on recovery/inactive state, and a later entry creates a new episode; historical facts survive delayed events without reopening stale alerts. |
| R9 | Create useful durable stubs | At most one low-stock stub per episode; resolved/superseded episodes produce a persisted skip outcome; baseline episodes suppress notifications; order/menu diagnostics are deduplicated. |
| R10 | Expose scoped alerts and history | Owners and assigned Managers see active alerts and paginated history only in scope; Employees cannot read inventory alerts; revoked access and cross-tenant requests are rejected. |
| R11 | Preserve correlation and inspectability | Request correlation accompanies events, relay, consumer attempts, and operator replay; safe structured output identifies event/consumer/attempt without secrets or customer payloads. |
| R12 | Demonstrate freshness honestly | Under a documented healthy local load, measure event commit-to-consumer completion against a five-second target; UI refreshes every 15 seconds while visible and after local stock actions. |
| R13 | Initialize and retain safely | Maintenance initialization/rebuild is repeatable, baseline provenance is explicit, no false historical transitions are emitted, and no automatic event/receipt/history deletion occurs in M8. |
| R14 | Validate and document the feature | Required failure/isolation/browser cases, clean/legacy migrations, static/build checks, and the full shared gate set pass with dated evidence and executable runbooks. |

Out of scope: external email/SMS/messaging, real payment processing, repeated
low-stock reminders, alert acknowledgement/dismissal, dashboard projection
cutover, full M11 analytics/timezone modeling, forecasts, RabbitMQ/Kafka,
microservices, deployment platforms, and full M10 observability dashboards.
Operational counters and correlation needed to prove M8 remain in scope.

## User experience

Place an active-alert section above the ingredient list on the existing inventory
page. Show ingredient name, current quantity, base unit, threshold, and episode
start time. Include a collapsible, paginated "Alert history" section with opening
quantity/threshold, start/resolution times, baseline provenance, and resolution
reason: stock recovery, threshold change, or archive. Restoring a low ingredient
starts a new episode. No dismiss/acknowledge controls or repeated reminders.

Alert reads use current `inventory.read` authorization and branch scope. Owners
cover their organization; Managers require assignment; Employees have no
inventory access. The API checks scope independently of the page's capability
check. Foreign/unassigned resources retain 404 behavior and forbidden
capabilities retain 403 behavior.

Load current quantities/thresholds from authoritative inventory when presenting
active alerts; retain immutable opening facts for history. Refresh alert data
every 15 seconds while the page is visible and after local stock actions. This is
a separate UI cadence from the five-second healthy processing target, so visible
updates can take longer than worker processing. Manual refresh remains available.
Avoid interrupting editors or losing entered form values during refresh.

The existing live low-stock indicators remain immediately useful while workers
catch up. Alert loading/error/stale states must be distinguishable from a
successfully loaded empty result. On failure, retain clearly marked last-known
data if available and show a retry action; do not report "no alerts".

Add scoped, paginated alert/history read contracts under the existing restaurant
inventory API namespace. Exact subpaths and response types are implementation
details to settle before coding that slice. Reuse browser/server API transports,
cookie/CSRF/renewal behavior, and existing error contracts. Consult installed
Next.js documentation as required by `frontend/AGENTS.md` before frontend code.

## Architecture and ownership

```text
API service-owned PostgreSQL transaction
  business state + ledger + audit + immutable event + consumer deliveries
                          |
                          v
Worker relay -> Redis Stream -> independent consumer groups
                                    |
                                    v
                  consumer effect + unique receipt (one DB transaction)
                                    |
                                    v
                              Redis acknowledgement

PostgreSQL recovery scan -> republish unfinished deliveries after loss/stall
```

One worker program initially runs separate relay, recovery, analytics, alert,
and notification/sink loops with bounded concurrency. It shares backend code,
not API request sessions. A dedicated worker Redis pool prevents competition for
the API's cache/auth pool. Existing API Redis timeouts and failure policies stay
intact; worker blocking-read budgets must be configured separately and bounded.
Use Redis 7-compatible commands, not features available only in newer releases.

Place event contracts and event/delivery orchestration in a cohesive events
module using `service.py`, pure `domain/` types, and `repo/` persistence. Keep
analytics persistence in analytics, inventory transition metadata in inventory,
and alert episode persistence in an alerts feature module. Add a notification
module only to house actual sink/stub behavior. Shared worker/Redis adapters sit
outside business domains. Exact filenames are implementation details; do not
create speculative layers or generic repositories.

Producers append through a public event service interface using the current
business transaction; repositories never commit. Consumer services own their
transactions and use explicit public feature interfaces. Inventory exposes the
transition/state check needed by order acceptance and alerts without expanding
the existing cross-feature ORM access pattern. No unrelated architectural
rewrite is included.

API startup neither launches workers nor migrates. Worker startup does not
migrate either. Shutdown stops claims and allows a bounded grace period for
current operations; unfinished work remains recoverable. A forced termination
must be safe without graceful shutdown. `/health` remains API liveness.

## Event contract

| Event | Trigger and necessary facts |
|---|---|
| `order.submitted.v1` | Actual DRAFT to SUBMITTED transition. |
| `order.accepted.v1` | Actual SUBMITTED to ACCEPTED transition with synchronous atomic inventory consumption. |
| `order.completed.v1` | Actual READY to COMPLETED transition; order total, creation timestamp, identity, and revision support analytics. |
| `order.cancelled.v1` | Actual allowed transition to CANCELLED; never reverses consumption. |
| `order.deleted.v1` | Permitted deletion, with identity/revision and facts needed to remove an analytics contribution even when the order is gone. |
| `menu.updated.v1` | Menu/item creation, edit, deactivation, or deletion; identifies the operation and affected menu/item. |
| `inventory.state_changed.v1` | Changed balance, threshold, or active state; includes resulting state, revision, and episode transition identity/facts where applicable. |
| `inventory.low.v1` | Entry into a low-stock episode; includes stable episode identity, opening state, and triggering revision. |

The last two additional state/deletion contracts and broader menu operation
semantics refine the roadmap's initial list. Events occur on genuine committed
changes, not read requests, same-state retries, no-op edits, idempotent command
replays, or rollback. Multiple events in one transaction share correlation.
Menu event delivery does not replace existing post-commit cache invalidation
or change M7's bounded-staleness policy.

Envelope: stable UUID event ID, canonical event type/schema version, verified
organization and restaurant scope, aggregate type/identity, aggregate revision,
UTC occurrence time, request correlation ID, and typed payload. Validate event
type/version consistency. Existing naive order creation timestamps require an
explicit UTC interpretation at the event boundary while preserving current
analytics date grouping. Do not silently convert existing storage or metric
semantics to restaurant local time.

Prices/quantities serialize losslessly as decimal strings. Capture sufficient
immutable business facts for replay without relying on mutable/deleted entities.
Exclude customer names, notes, credentials, cookies, raw headers, and arbitrary
request bodies. Actor identity is provenance only, never worker authorization.
Consumers dispatch by a fixed registry; payloads cannot select arbitrary code.

Redis messages contain the stable event ID and minimal routing metadata; the
authoritative typed payload is loaded from PostgreSQL. Redis stream message IDs
identify deliveries, not business events. Republish keeps the event UUID while
allowing a new stream ID. Missing or conflicting event references require safe
diagnostics and cannot create effects from untrusted Redis metadata.

## Durable delivery and duplicate protection

Logical persistence consists of immutable outbox facts; mutable per-consumer
delivery state; unique successful receipts; and consumer-owned effects. Required
consumer deliveries are recorded with event creation using a fixed subscription
registry, preventing a crash between event commit and fan-out initialization.

Delivery state includes consumer/event identity, status, attempt count,
next-attempt time, claim/lease information, publication observation, and safe
last-error category. A receipt is unique on `(consumer, event_id)`. Database
constraints enforce identity/scope consistency where applicable. Event/history
references must not cascade away on business-object deletion.

Use one namespaced stream initially and independent consumer groups for the
analytics, alert, and notification/sink responsibilities. Workers within one
group share messages; groups independently consume the stream. Non-subscribed
event types are acknowledged without business effects. Recovery targets only
unfinished subscribed deliveries even if a republished message reaches several
groups. Successful receipts make that fan-out harmless.

Claims use short database transactions and nonblocking row selection such as
`FOR UPDATE SKIP LOCKED`, with expiring claims and ownership checks so an old
worker cannot overwrite a newer claim. Do not hold business row locks during
Redis/network I/O. Consumer receipt/effect transactions serialize competing
attempts through uniqueness and appropriate row locks; a preliminary receipt
read alone is not sufficient to prevent duplicates.

Commit consumer effect, receipt, and successful delivery state together, then
acknowledge Redis. A crash before commit leaves no effect; a crash after commit
but before acknowledgement leads to a harmless receipt-checked replay. Outcomes
that deliberately skip a stale notification also have a durable receipt.

Publication does not mean completion. PostgreSQL recovery scans unfinished
deliveries and republishes after loss or expired/stalled attempts, with bounded
scan rate and leases to avoid message floods. Recover Redis pending messages
from crashed consumers, recreate lost groups/streams, and reconcile PostgreSQL
work after Redis restart. Ambiguous publish/acknowledgement outcomes may produce
duplicates but must not lose events. Persisted due times remain authoritative
when Redis redelivers a message early.

## Consumer semantics

### Analytics

Maintain completed-order count and completed sales total by restaurant and order
creation date, matching current live SQL. Store each order's projected
contribution and applied revision so completion replaces a contribution rather
than blindly incrementing a counter. Deletion removes it and leaves a revision
tombstone that prevents an older completion event from resurrecting it.

Receipts, contribution/tombstone, and daily aggregate deltas commit atomically.
Different orders updating the same day's row must not lose increments. Fixed
precision is retained. Keep item/category/timezone/refund analytics for M11.
No projection-based dashboard cutover or performance improvement is claimed.

Provide inspectable projection output and comparison to authoritative SQL.
Initialization/rebuild seeds current order facts and revision watermarks safely
against already queued events; a baseline plus old queued completion must not
double count. Rebuild is a maintenance operation, not "delete all receipts and
replay". Existing receipts remain truthful, and rebuilt contribution revisions
prevent older queued work from undoing the baseline.

### Inventory alerts

Low means active and `quantity <= reorder_threshold`, including zero at a zero
threshold. Creation with low opening stock opens an episode. Further deductions
while low update state without new episodes or notifications. Stock above the
threshold resolves; threshold edits reevaluate; archive resolves; restoration
while low opens a new episode. Cancellation has no stock effect and creates no
inventory recovery.

Inventory owns monotonic state revisions covering balance, threshold, and
active-state changes, plus stable opening/closing episode transition metadata
captured under the existing restaurant lock. Keep the current balance version's
physical-count contract intact. Episode identity must be available from the
producer's durable transition facts, not invented by arrival order in a worker.

The alert projection preserves historical opening/resolution facts even if
resolution arrives first. A stale event may fill history but cannot replace
newer current state. For example, revision 10 opens and revision 11 resolves;
late revision 10 must not reopen the alert. Preserve history snapshots through
ingredient renames/archive and derived-data rebuild.

### Notification and diagnostic sink

One low-stock notification stub per episode, protected by a unique episode key.
Before creating it, check authoritative active/low state and current episode
identity under the same restaurant lock used by stock writes. Record stub or
skip outcome and receipt atomically. Never hold that lock during external I/O.

The timing boundary is the stub transaction commit: the episode was current and
low then. Replenishment afterward resolves the alert without erasing the
historical stub. If replenishment/supersession occurred first, record a skip
instead of a stale notification. Initialization baseline episodes suppress stubs.

Order lifecycle, deletion, and menu events produce deduplicated durable diagnostic
sink records. These are operator-inspectable facts, not new customer-facing
notifications. Structured logs support diagnosis but are not the idempotent
effect: a log can repeat or be absent around a crash. Future external providers
require their own delivery/idempotency design and current recipient access checks.

## Failure handling, operations, and correlation

| Condition | Agreed response |
|---|---|
| PostgreSQL/Redis/shared dependency outage | Pause affected work with bounded backoff and recovery probes; do not spend every event's poison allowance on the outage. Other unaffected loops may continue. |
| Event-specific transient failure | Eight total processing attempts, configurable; start at one second, exponential increase to a 60-second cap, with small bounded jitter. Persist attempt/due state. |
| Unsupported version or invalid payload | Retain as failed work immediately with a clear safe reason; unchanged retries cannot repair it. |
| Worker termination or expired claim | Recover/reclaim without relying on shutdown; receipt and revision checks protect effects. |
| Poison event reaches attempt limit | Mark that consumer delivery failed in PostgreSQL; keep event and successful consumers intact. |
| Replay after repair | Requeue only the selected failed delivery with the same event ID/payload, record operator/reason, and begin an explicit new retry cycle. Preserve earlier attempt history and receipts. |

Distinguish infrastructure availability from event-caused database errors;
constraint/payload failures are not grounds to pause all work indefinitely.
Retry classification, recovery scan intervals, claim duration, jitter range,
and concurrency limits need concrete conservative values during implementation
and failure testing; they cannot weaken the agreed attempt/cap/recovery behavior.

CLI responsibilities: status (pending depth, oldest age, retries, failed counts,
retained counts by consumer); inspect (identity, scope, version, attempts, safe
reason); replay one failed consumer; analytics reconcile/rebuild; and maintenance
initialization. CLI names/flags are not yet executable contracts. Restrict CLI
access through trusted operator environment/database credentials; a free-form
operator label is provenance, not authorization. Persist replay actor/provenance,
reason, time, and delivery identity.

Background handlers process previously authorized committed facts, not the
original user's command; later user revocation does not erase that fact. Workers
use narrowly defined internal operations, not fabricated Owner principals.
All user-facing reads resolve current membership, assignment, and capabilities.

Propagate existing request correlation through envelope and worker context;
include event ID, consumer, attempt, and safe failure category in structured
logging. Replay retains original correlation and adds replay-operation identity.
Extend the logging allowlist deliberately. Do not log credentials, Redis URLs,
customer payloads, or unsanitized driver exceptions. Full trace infrastructure
is deferred to M10; M8 preserves correlation and any supported safe trace context.

## Migration, initialization, retention, and rollout

Use new additive Alembic revisions for event/delivery/receipt tables, inventory
state revisions/episode transition metadata, order revisions, projections,
alert history, and sink records. Register every model; maintain one head. Review
generated SQL, constraints/indexes, populated-database defaults, preservation,
and downgrade guards. Downgrade must not silently discard event/replay/history
data. Avoid destructive rewrites of orders, movements, or existing audit facts.

Explicit application cutover uses a short maintenance window:

1. Pause business writes and stop workers; quiesce any in-flight writes.
2. Inspect actual application Alembic revision and take the runbook backup.
3. Apply the additive migrations as an explicit operation.
4. Initialize analytics from existing orders with revision watermarks.
5. Create baseline episodes for currently active low ingredients, labelled
   "low at initialization"; start time is observation time, not invented history.
6. Persist baseline notification suppression, start workers, and resume writes.

Initialization must be repeatable and must not recreate resolved baseline
episodes on rerun. Persist a scoped initialization marker/provenance. Existing
pending events and successful receipts are preserved. Do not emit invented
historical order transitions. Already low baseline ingredients remain suppressed
until recovery followed by a genuinely new low episode.

Retain outbox events, delivery/attempt records, receipts, diagnostic/stub records,
and alert history throughout M8. No automated deletion or stream trimming is
introduced initially. Report PostgreSQL retained counts and Redis stream size
so both database and Redis memory growth are visible. Storage growth is an
accepted limitation, not an unlimited production-retention promise. Future
cleanup must coordinate receipt/event lifetime, replay eligibility, history
references, and stream pending entries.

Redis remains recoverable transport with existing local persistence disabled.
No application database migration occurs during validation. Disposable testing
uses isolated Compose namespaces/ports/databases and preserves the developer
PostgreSQL volume. Deployment platforms and production rollout infrastructure
remain M9 work.

## Decisions, alternatives, and evidence

| Decision | Rationale and alternative |
|---|---|
| Redis Streams plus PostgreSQL recovery authority | User chose Streams to learn and use existing Redis. Direct PostgreSQL delivery would be simpler but would defer the requested transport. Redis publication alone is insufficient with current nonpersistent Redis. |
| Separate groups, one worker program initially | Consumers fail independently without introducing independently deployed services; multiple workers can later share group work. |
| Durable per-consumer completion | A published flag cannot prove every consumer finished. Receipts plus recovery scans survive transport loss and ambiguous publication. |
| Revisions and episode identities | Receipts prevent duplicates; revisions separately prevent older events from overwriting newer facts. Global event ordering is unnecessary. |
| Small analytics projection, live dashboard | Proves asynchronous correctness without changing freshness expectations or prematurely taking over M11 metrics. |
| Durable stub/sink rather than log-only effect | Database uniqueness makes effects testable; exactly-once ordinary logs or external notifications are not claimed. |
| Maintenance initialization and no initial pruning | Simplifies safe baselines and replay while accepting visible storage growth and a brief write pause. Online rebuild/cutover and retention require later designs. |

Technical references checked during planning:
[Redis Streams](https://redis.io/docs/latest/develop/use-cases/streaming/)
documents group acknowledgements and pending-message recovery;
[Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
explains persistence options; and
[PostgreSQL 16 SELECT](https://www.postgresql.org/docs/16/sql-select.html)
documents `SKIP LOCKED` for queue-like consumers. These establish mechanism
availability, not proof that RestaurantOS implements this design correctly.

## Validation and acceptance evidence to produce

All checks below are planned and unexecuted for M8.

| Check | Requirements and success signal |
|---|---|
| Transaction rollback injection | R1/R2: failed audit/event/delivery insert leaves no business change, stock movement, or partial event. |
| API crash after DB commit, before publication | R3: worker subsequently produces every subscribed effect from the committed outbox. |
| Ambiguous publication and Redis restart/content loss | R3/R4: recovery rebuilds transport work; each consumer effect remains unique. |
| Consumer crash before commit and after commit/before ACK | R3/R4: uncommitted effect retries; committed effect is receipt-checked. |
| Concurrent duplicate consumers | R4: prove overlap using barriers/locks, not sleeps; one receipt/effect, correct aggregate deltas. |
| Temporary dependency outage and poison failures | R5/R6: recovery does not exhaust unrelated events; eight event-specific attempts produce inspectable failure and safe replay. |
| Unsupported schema/version | R5/R6: clear retained failure, no unsafe effect or endless hot loop. |
| Out-of-order open/resolve/new episode | R8/R9: history is complete, old state never becomes current, obsolete stub is skipped. |
| Replenishment vs notification overlap | R8/R9: shared-lock timing boundary is proven; no stale episode stub commits after prior resolution. |
| Analytics completion/deletion/rebuild overlaps | R7/R13: tombstones/watermarks prevent resurrection or double count; concurrent orders do not lose daily updates. |
| Maintenance initialization and rerun | R13: correct existing totals, truthful baseline episode facts, suppressed startup stubs, preserved receipts and no duplicate baseline episodes. |
| Tenant/role/revocation cases | R10: direct/nested/list/count/history reads remain scoped; foreign 404 and forbidden 403 contracts preserved. |
| Inventory component and Chromium workflows | R10/R12: active/history, pagination, stock recovery, refresh, errors/empty states, permissions, and form preservation work against real API. |
| Healthy-load processing measurement | R12: record workload, environment/revisions, commit-to-effect latency distribution and target misses; assess the five-second target without claiming outage guarantees. |
| CLI and shutdown exercises | R6/R11: safe status/inspect/replay, audit provenance/correlation, graceful and forced recovery; no sensitive diagnostics. |
| Clean/seeded legacy migrations | R13/R14: one head, model drift check, data preservation and downgrade guards in disposable databases. |

Implement regressions at the affected layer using real PostgreSQL and Redis for
integration behavior. Unit tests cover pure transition/retry/version rules without
services. Integration gates must exercise actual worker processes for required
crash/restart scenarios, not only handler mocks. Add image smoke coverage for the
worker entrypoint if the runtime image is extended.

Run affected backend unit/integration/static, frontend tests/static/build,
browser, migrations, and image gates as slices land. Milestone acceptance requires
the full root `./scripts/validate.ps1` command on Windows (or the documented
Python runner on Linux/macOS) and complete CI under the unchanged
`Milestone 6 acceptance` aggregate. Partial/historical runs cannot establish M8
completion. Extend existing gates to include worker coverage rather than leaving
it optional. Retain failure-cleanup and test database guards.

Update event/alert API contracts, worker commands/configuration, initialization,
backlog/replay/Redis-loss/rebuild runbooks, testing regression maps, current-state
evidence, and roadmap status during implementation within that scope. Report
actual commands, outcomes, omissions, revision, schema changes, and limitations.

## Delivery sequence and remaining implementation choices

1. Event contracts, additive schema, and transactional producer integration.
2. Redis relay, consumer groups, claims, and recovery from transport loss.
3. Atomic receipts, persisted retries, failed-work inspection, and replay.
4. Analytics contribution/aggregate projection, initialization, rebuild, reconcile.
5. Inventory transition metadata, alert history, stubs/sink, and inventory UI.
6. Full failure exercises, measured freshness, runbooks, and shared validation.

Each slice must be coherent and tested; the sequence is not authorization to
leave early slices without critical failure coverage. Producer revision metadata
needed by later consumers is designed in the first slice.

No high-impact planning decisions remain open. Low-impact implementation choices
remain: exact module/table/API/CLI names, typed payload field names, batch/pool
sizes, recovery intervals/leases, worker grace time, bounded jitter, history page
size, and the concrete measured workload. Record their selected values and
evidence before claiming acceptance. Material changes to agreed semantics or
scope require a proposed design revision and user acceptance.

## Decision history

| Date | Accepted decision and approval evidence |
|---|---|
| 2026-10-11 | Redis Streams and proposed consumer scope: user chose Redis because it is already present and requested guidance. |
| 2026-10-11 | One low-stock episode until recovery, then a new episode: "That alert behavior is perfect." |
| 2026-10-11 | Inventory-page alert section: "Include that inventory page alert section in M8." |
| 2026-10-11 | Daily completed-sales/count projection with dashboard on live SQL: "Yea that works for me." |
| 2026-10-11 | Retry defaults, operator CLI recovery, and freshness targets: user agreed and requested documentation after planning. |
| 2026-10-11 | Historical episodes without stale current alerts; atomic notification timing rule: user explicitly accepted the history and stale-alert behavior. |
| 2026-10-11 | History UI, retained records, maintenance initialization, and baseline notification suppression: "Yes let's go with that." |
| 2026-10-11 | Final event/consumer arrangement and implementation boundaries: "I accept. Planning is settle then." Revision 1 records this accepted baseline. |
| 2026-10-11 | User authorized this document path and a commit; no production implementation or external publication was requested in this turn. |
