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
