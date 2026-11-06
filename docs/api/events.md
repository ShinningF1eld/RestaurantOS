# Domain event and delivery contracts

Operational freshness is measured at committed consumer receipt visibility;
event occurrence/recording and receipt timestamps are not commit timestamps.
The [measurement procedure](../testing/event-freshness-benchmark.md) and
[dated results](../milestone8/performance-milestone8.md) report the five-second
healthy target without an outage guarantee. Existing HTTP contracts are unchanged.

This contract defines the PostgreSQL outbox records introduced for Milestone 8
Issues #31–#35, including Redis Streams transport and consumer orchestration. Events are immutable facts.
Producers append an event and its fixed consumer delivery rows in the business
command's existing transaction through `app.modules.events.service.append_event`;
the events repository never begins, commits, or rolls back a transaction. The
standalone T4 worker relays stable event UUID references to Redis Streams, while
PostgreSQL remains authoritative for event facts and unfinished delivery state.
T5 supplies atomic effect/receipt execution, persisted retries and operator replay.
T6 installs the completed-sales/deletion analytics handler; see the
[projection contract](analytics-projection.md). T7 installs revisioned alert
history/current-state projection, durable per-episode notification outcomes,
and deduplicated order/menu diagnostic records; see the
[alert and sink projection contract](alert-projection.md).

## Envelope

Every envelope contains:

| Field | Type and rule |
|---|---|
| `event_id` | Stable UUID, generated once by the producer and retained across delivery/replay. |
| `event_type` | One of the eight names below; the `.v1` suffix agrees with `schema_version: 1`. |
| `schema_version` | Integer `1`; unsupported types and versions are rejected. |
| `organization_id`, `restaurant_id` | Organization UUID and restaurant ID verified as a matching persisted scope pair before append. |
| `aggregate_type`, `aggregate_id` | `order`, `menu`, `menu_item`, or `ingredient`; string identity must agree with the typed payload. No FK points at deletable business entities. |
| `aggregate_revision` | Positive monotonic producer revision for that aggregate. Order rows store `revision`; inventory producers use `InventoryTransition.state_revision`. Catalog revisions count emitted changes, allocated from retained scoped aggregate events under the restaurant write lock. |
| `occurred_at` | A timezone-aware timestamp normalized to UTC. |
| `correlation_id` | Request correlation identifier (1–128 safe characters); one business command's events share it. |
| `payload` | Versioned typed object containing only the facts listed below. Decimal quantities and money are serialized as base-10 strings. |

For order `created_at`, a legacy naive database timestamp is interpreted as UTC
at the event boundary. This preserves the existing `created_at::date` grouping;
it does not introduce restaurant-local-time grouping. Event occurrence times
and inventory episode timestamps must carry a UTC offset.

Contracts reject extra payload fields. They do not include customer names or
notes, credentials, cookies, headers, actor authorization claims, or arbitrary
request bodies. Menu events carry identities and operation names, not mutable
menu content. Redis stream entries contain only event UUID, event type, schema
version and correlation ID. They cannot choose a handler or replace PostgreSQL
facts.

## Typed payloads

| Event | Payload fields |
|---|---|
| `order.submitted.v1` | `order_id`, resulting `status: SUBMITTED`. |
| `order.accepted.v1` | `order_id`, resulting `status: ACCEPTED`. Inventory consumption is already committed synchronously with acceptance. |
| `order.completed.v1` | `order_id`, authoritative `total` decimal string (at most 99,999,999.99), and `created_at` timestamp. These facts support the existing completed-sales grouping. |
| `order.cancelled.v1` | `order_id`, resulting `status: CANCELLED`. Cancellation never restores stock. |
| `order.deleted.v1` | `order_id`, `prior_status`, authoritative `total`, and `created_at`; enough to identify and remove a completed-order contribution after deletion. |
| `menu.updated.v1` | `operation` (`created`, `edited`, `deactivated`, `deleted`), `target_type` (`menu` or `menu_item`), `target_id`, `menu_id`, and unique `affected_menu_item_ids`. |
| `inventory.state_changed.v1` | `ingredient_id`, immutable `ingredient_name` and `unit`, resulting `quantity` and `reorder_threshold` decimal strings (at most 999,999,999.999), `is_active`, derived `is_low`, current/transition `episode_id`, `episode_transition` (`opened` or `resolved`), and `resolution_reason` (`stock_recovered`, `threshold_changed`, or `archived`) when resolved. `is_low` must equal active and quantity at or below threshold. |
| `inventory.low.v1` | Stable `ingredient_id` and `episode_id`, immutable ingredient name/unit, opening quantity and threshold as decimal strings, and UTC `opened_at`. Envelope revision is the triggering inventory state revision. |

## Trigger and no-op matrix

| Event | Trigger | No event for |
|---|---|---|
| `order.submitted.v1` | Actual DRAFT → SUBMITTED transition. | Reads, invalid transitions, unchanged status, or rolled-back command. |
| `order.accepted.v1` | Actual SUBMITTED → ACCEPTED transition after synchronous stock consumption. | Repeated ACCEPTED status, idempotent replay, or failed inventory/audit write. |
| `order.completed.v1` | Actual READY → COMPLETED transition. | Repeated COMPLETED status, read, or rollback. |
| `order.cancelled.v1` | Actual permitted transition to CANCELLED. | Repeated CANCELLED status; cancellation does not produce stock recovery. |
| `order.deleted.v1` | Permitted order deletion; snapshot is appended before the row is removed. | Rejected deletion or rollback. |
| `menu.updated.v1` | Actual menu/item create, edit, deactivation, or deletion. | Read, same-value/no-op edit, command replay, or rollback. Existing post-commit cache invalidation remains separate. |
| `inventory.state_changed.v1` | Actual balance, reorder threshold, or active-state change. Includes resulting state/revision and relevant episode facts. | No-op update, same idempotent command replay, or rollback. |
| `inventory.low.v1` | Entry into a new low-stock episode (`active AND quantity <= reorder_threshold`). | Further changes during the same episode, zero-effect writes, cancellation, or rollback. |

Multiple events produced by one command use the same request correlation ID.
Trusted service commands outside HTTP generate one fallback correlation per
command. Issue #33 integrates producers into existing service-owned transactions;
API startup and commands neither publish transport messages nor launch workers.
Order revisions advance once per actual changed order command, including
PREPARING/READY and non-status edits that do not emit lifecycle events. No-op
commands do not advance the order revision. Deletion emits the next revision
before removing the row, so its tombstone supersedes prior completion facts.
Catalog revisions start at one for the first emitted change to each menu/item;
retained events provide the watermark even after deletion. All catalog writers
serialize allocation/append with the restaurant lock and refresh locked state
before no-op comparison. No schema or API response fields were added in T3.

Inventory episode contracts reject contradictory boundary facts: an `opened`
transition requires a low resulting state and episode identity; a `resolved`
transition requires a non-low resulting state, episode identity and resolution
reason. A low-stock opening quantity must be at or below its threshold,
including zero at a zero threshold. The public inventory producer transition
type also checks opened/resolved boundaries. A legacy producer snapshot without
a boundary may remain low without an episode ID until maintenance initialization;
an ordinary change may emit a low-state payload with `episode_id: null` and no
boundary until maintenance initialization. This preserves truthful legacy state
without inventing an episode or emitting `inventory.low.v1`; an `opened` boundary
still requires an episode ID. Initialization itself emits no historical event.

## Fixed subscription matrix

The registry is code-owned and immutable. T4 creates one Redis consumer group for
each registry consumer: `analytics`, `alerts`, and `notification_sink`. The
transport checks the PostgreSQL event and fixed registry before routing. T5
executes registered handlers through a fenced service-owned transaction;
unimplemented handlers leave subscribed references pending without fabricated
effects. The analytics, alerts and notification-sink consumers are now all
implemented.

| Event | Analytics | Alerts | Notification/diagnostic sink |
|---|:---:|:---:|:---:|
| `order.submitted.v1` |  |  | ✓ |
| `order.accepted.v1` |  |  | ✓ |
| `order.completed.v1` | ✓ |  | ✓ |
| `order.cancelled.v1` |  |  | ✓ |
| `order.deleted.v1` | ✓ |  | ✓ |
| `menu.updated.v1` |  |  | ✓ |
| `inventory.state_changed.v1` |  | ✓ |  |
| `inventory.low.v1` |  | ✓ | ✓ |

Analytics handles completed-order contributions and deletion tombstones. Alerts
handles revisioned state and episode history. The sink records deduplicated
diagnostic facts and one low-stock notification outcome per episode; no external
messaging is part of this contract.

## Durable records and transaction boundary

`outbox_events` stores immutable JSONB facts and scope; PostgreSQL triggers reject
updates and deletes. `event_deliveries` stores one required row per fixed
subscription with due time, claim lease/ownership token, publication observation,
attempt count, retry cycle, and safe error category. `event_receipts` has one
`(consumer_name, event_id)` key. `event_delivery_attempts` and
`event_delivery_replays` retain cycle-level processing and operator replay
history. Database triggers reject mutation of event/receipt/replay facts and
deletion of delivery/attempt history. Foreign keys among retained event facts use `RESTRICT`; event rows do
not reference orders, menu items, or ingredients and survive those deletions.
The restaurant/organization composite FK rejects a mismatched tenant scope.

The service requires an active caller-owned transaction, verifies the restaurant
scope, stages the immutable event and every subscribed delivery, and flushes.
Any fan-out/constraint error propagates so the caller's transaction can roll
back completely. Repositories do not commit. The T4 worker publishes minimal
references after claiming delivery rows in PostgreSQL; `published_at` is only a
transport observation, never business completion. A consumer can replace the
relay's claim and commit success before that observation is recorded; the stale
relay update is then fenced out and `published_at` can remain null even on a
succeeded delivery. Use delivery status and the committed receipt to determine
processing completion. No automatic pruning or Redis stream trimming is introduced.


## T5 execution and operator recovery

`events.execution.ConsumerExecutionService` owns short persisted attempt claims
and effect transactions. Delivery locks and claim tokens serialize duplicates;
the effect, processed/skipped receipt and success commit together before ACK.
The default allowance is eight attempts per cycle with persisted exponential
backoff, 0–10% jitter and a 60-second cap. Crashed started attempts count;
observed shared outages retain diagnostic history without consuming allowance.
Unsupported contracts/invalid payloads fail immediately. Retained history records
ordinals independently from the charged `attempt_count`.

`python -m app.modules.events.cli status|inspect|replay` uses trusted database
credentials. Replay selects one failed delivery UUID and requires `--reason`;
it records the database-authenticated role, timestamp and replay identity while
preserving the event, original correlation and all earlier history. Safe output
omits payloads, free-form reasons and raw errors. See the
[worker runbook](../runbooks/event-worker.md) for commands and failure semantics.
No HTTP API or schema migration is added by T5.

## T8 maintenance operations

`initialize` and `analytics-rebuild` add trusted scoped offline reconstruction;
see the [maintenance runbook](../runbooks/event-maintenance.md) for exact flags,
backup/migration sequence and interruption recovery. Additive revision
`c3d8e1f52a74` creates `event_maintenance_operations`: one uniquely indexed
initialization marker per restaurant plus retained rebuild provenance, with a
restrictive organization/restaurant foreign key. It stores operation UUID,
kind, database-authenticated role, required reason and observation time, without
rewriting business data or generating historical events. Downgrade rejects
retained provenance. Initialization, projection seeding, suppressed baseline
facts and the marker commit atomically; an initialization rerun returns the
existing marker without regenerating episodes or resetting deliveries/receipts.

## Restart-safe worker telemetry (M9 issue #62)

`outbox_events.traceparent` is nullable `varchar(55)` metadata, independent of
schema-version-1 envelopes and `correlation_id`. Append captures the active
recording OpenTelemetry span, validates exact lowercase W3C version `00`, nonzero
128-bit trace/64-bit span identifiers and one byte of flags, and flushes it in
the existing business transaction. Missing, nonrecording, malformed or unavailable
context becomes NULL. No headers, baggage, tracestate or payload content is
stored in this field. Existing immutable-row protection also protects it.

PostgreSQL claims and attempt startup load this metadata; Redis references remain
unchanged and cannot supply authoritative context. `outbox publish` (PRODUCER)
and `consumer attempt` (CONSUMER) are independent root spans with at most one Link
to that context. Local ALWAYS_ON sampling deliberately ignores the incoming
sampling decision, including for unsampled links, as in the existing acceptance
configuration. No HTTP span waits for a worker. Safe attributes are event ID/type,
consumer, correlation ID, publication delivery/claim IDs, execution attempt ID/
number, retry cycle and replay ID. Outcomes and allowlisted failure categories
are added after the actual operation. Exception text and events are excluded.

Publication distinguishes `published`, `claim_lost`, `transport_failure`,
`observation_failure` and interruption. Success requires both the actual Redis
publication and its fenced database observation. Each durable execution claim
gets a separate span, ending after effect/receipt commit or failure settlement:
`consumer_committed`, `consumer_retry_scheduled`, `consumer_failed`,
`claim_superseded`, `claim_expired` or interruption. Attempts share event identity;
retry/replay identities distinguish them. Duplicate receipts and busy routing
checks are separate routing metrics/local structured logs, not effect attempts.

Worker startup reuses `MONITORING_*`, the process-owned lifecycle, bounded batch
queues, HTTP timeouts and daemon shutdown retirement. Telemetry does not export
synchronously from append, claim, effect or settlement transactions. Shutdown
waits at most `MONITORING_SHUTDOWN_SECONDS`; collector failures never gate commits,
receipts or ACKs. SDK export/queue diagnostics and local JSON worker logs remain;
loss diagnostics are best effort and may themselves disappear on process death.

Persisted identifiers survive independently of Tempo's three-day retention.
Tempo may have expired the original request. Identifiers cannot reconstruct lost
span data; authorized event/correlation/attempt diagnostics remain useful.

Migration `d4e9f2a63b85` adds this nullable column and a covering partial delivery
index for unfinished/terminal aggregate reads, with no backfill, event
payload change or historical trace fabrication. Its downgrade drops only trace
metadata and the new observability index. Deploy compatible application code before downgrading to
`c3d8e1f52a74`; current ORM code requires the column. Application migrations remain
an explicit backup/runbook operation; validation uses disposable databases only.
The transactional index build can block concurrent delivery writes during an
explicit migration; schedule it appropriately. The covering index adds write
maintenance for changing claims/due times in exchange for excluding completed
history from collection.

### Worker metric producer slots

`MONITORING_WORKER_SLOT` is optional and bounded to integers **0–31**. Assign a
**different slot to each concurrent worker** sending to the same Collector. This
is an operator assignment, not an event, tenant or randomly generated process ID.
Do not run concurrent processes with the same slot. Stop the previous owner
before reusing a slot; counters then reset normally within that slot. No database
lease or automatic distributed slot allocator is introduced.

When a slot is assigned, event process counters/histograms and worker SQL/Redis/
pool diagnostics include the bounded `worker_slot` dimension. Collector admission
validates the range and preserves it for these process streams. Compute service
rates per slot first, then sum rates; do not sum cumulative values across restarts.
For example `sum(rate(restaurantos_worker_operations_total{operation="consumer",outcome="consumer_committed"}[5m]))`.
Native tests retain independent 5/9-operation streams through quiet re-export and
reset only slot 0 to 1 on restart while slot 1 stays at 9.

Without a slot, traces, local JSON diagnostics and durable backlog/recent-receipt
snapshot gauges remain available, but worker **process-local metrics are not
recorded**. Startup emits the safe warning `worker process metrics require slot`.
This avoids silently merging unspecified producers into a fictitious counter.
Durable gauges never acquire a slot label: replicas describe the same PostgreSQL
facts and must not multiply those facts. API instrumentation is unchanged.

The pinned Python OTLP encoder serializes link trace/span IDs and remote-context
bits but omits the low W3C trace flags from wire links. Full validated flags remain
in outbox metadata and the constructed SDK `Link.context`; local ALWAYS_ON worker
sampling is independent. Tests verify both layers. No expired Tempo span can be
reconstructed from either representation.

### Worker metrics

SDK names below use dots. Collector Prometheus translation replaces dots with
underscores and adds unit/type suffixes (for example
`restaurantos_worker_operations_total`, `restaurantos_worker_duration_seconds`).
Process-local rows below also have `worker_slot` (0–31); durable gauge rows do not.
All metrics carry the bounded worker service resource. No business/trace/attempt
identity, raw exception, tenant, SQL parameter or payload is a metric label.

| SDK name | Type / unit | Dimensions | Meaning and source |
|---|---|---|---|
| `restaurantos.worker.operations` | Counter / 1 | operation (`publish`, `consumer`), consumer, event_type, outcome | Process observations of completed publication/claimed execution lifecycles; retries and replay are attempts, never new business events. |
| `restaurantos.worker.duration` | Histogram / s | same | Monotonic elapsed operation time including fencing/commit/settlement; excludes waiting for publication concurrency and initial execution claim acquisition. |
| `restaurantos.worker.routes` | Counter / 1 | consumer, outcome (`duplicate`, `busy`, `terminal`, `delayed`, `other`) | Routing checks with no new execution claim. Duplicate ACKs are not successful effects. |
| `restaurantos.worker.deliveries` | Gauge / 1 | consumer, state | Durable PostgreSQL delivery depth by operational state below. Sum queued/in_flight/retry_delayed/recovery_due for unfinished depth; terminal is separate. |
| `restaurantos.worker.oldest` | Gauge / s | consumer, state | Database-clock age since oldest delivery creation; zero for empty states. Maximum over unfinished states gives oldest unfinished age, not Redis message age. |
| `restaurantos.worker.receipts.window` | Gauge / 1 | consumer | Durable receipts whose recorded processing time falls in the previous five minutes; divide by 300 for approximate receipt throughput/second. Includes processed/skipped receipts; dedup/replay cannot add duplicate receipts. |
| `restaurantos.worker.receipts.latest` | Gauge / s | consumer | Newest recorded receipt Unix timestamp within that five-minute window; zero if absent, not a freshness guarantee. |
| `restaurantos.worker.collected` | Gauge / s | none | Process Unix time when the last backlog collection succeeded. |
| `restaurantos.worker.collection.failures` | Counter / 1 | worker_slot | Failed/timed-out aggregate collection attempts, separate from worker business failures. |

State precedence: failed is `terminal`; any active relay or consumer lease is
`in_flight`; processing with an expired/missing lease is `recovery_due`; pending
with future due time is `retry_delayed`; remaining pending is `queued`. Expired
relay claims become queued/delayed by due time. Succeeded deliveries are excluded.
Unfinished age includes active and delayed work, so a healthy scrape does not
mean work has drained. Terminal age is never silently included in eligible work.

Aggregate collection runs every 15 seconds in an independent worker task, with a
three-second overall budget and one-second SQL statement timeout. Queries exclude
completed delivery history and use a covering partial delivery index and the existing receipt-time index;
receipt progress scans only the recent window. State depth/age aggregation cost
still grows with unfinished/terminal backlog; timeouts retain the previous
snapshot and increment collection failures. PostgreSQL is authoritative, not
Redis stream length or process counters. Gauges are sampled snapshots and may
be stale; compare `collected` with wall time and missing-source signals. Backlog
and receipt queries are separate short read transactions, not an atomic
cross-table freshness proof. All replicas observe the same durable backlog:
never sum durable gauges across workers. Collection timestamps do not establish
projection progress or financial accuracy. Use existing projections/reconciliation
for retained sales, whose creation-date UTC semantics remain unchanged.

Process counters/histograms reset on restart and may lose observations on crashes,
queue overflow or exporter outage; they are not durable accounting. Durable
snapshot gauges recover from PostgreSQL after restart, but exports can be missing
or expire after the Collector's 30-second inactivity expiry. Empty groups are
explicitly emitted as zero. Receipt timestamps are recorded before transaction
commit and are not exact commit-time measurements. Telemetry has no backup.
