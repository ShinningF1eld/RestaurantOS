# Domain event and delivery contracts

This contract defines the PostgreSQL outbox records introduced for Milestone 8
Issue #31. Events are immutable facts. Producers append an event and its fixed
consumer delivery rows in the business command's existing transaction through
`app.modules.events.service.append_event`; the events repository never begins,
commits, or rolls back a transaction. Redis is not authoritative and is not used
by this slice.

## Envelope

Every envelope contains:

| Field | Type and rule |
|---|---|
| `event_id` | Stable UUID, generated once by the producer and retained across delivery/replay. |
| `event_type` | One of the eight names below; the `.v1` suffix agrees with `schema_version: 1`. |
| `schema_version` | Integer `1`; unsupported types and versions are rejected. |
| `organization_id`, `restaurant_id` | Organization UUID and restaurant ID verified as a matching persisted scope pair before append. |
| `aggregate_type`, `aggregate_id` | `order`, `menu`, `menu_item`, or `ingredient`; string identity must agree with the typed payload. No FK points at deletable business entities. |
| `aggregate_revision` | Positive monotonic producer revision for that aggregate. Order rows now store `revision`; inventory producers use `InventoryTransition.state_revision`. |
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
menu content. Redis messages, when introduced later, may carry routing hints but
cannot choose a handler or replace the PostgreSQL payload.

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

Multiple events produced by one command use the same correlation ID. This issue
defines contracts and persistence only; business event emission and inventory
transition persistence land in later M8 tasks.

Inventory episode contracts reject contradictory boundary facts: an `opened`
transition requires a low resulting state and episode identity; a `resolved`
transition requires a non-low resulting state, episode identity and resolution
reason. A low-stock opening quantity must be at or below its threshold,
including zero at a zero threshold. The public inventory producer transition
type also checks opened/resolved boundaries. A legacy producer snapshot without
a boundary may remain low without an episode ID until maintenance initialization;
it is not an emitted low-state payload.

## Fixed subscription matrix

The registry is code-owned and immutable. Consumer names here identify future
worker responsibilities, not worker execution in Issue #31.

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
diagnostic facts and one low-stock notification stub per episode in a later
slice; no external messaging is part of this contract.

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
back completely. Repositories do not commit. No automatic pruning or Redis
publication is introduced.
