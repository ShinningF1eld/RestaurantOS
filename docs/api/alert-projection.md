# Alert and notification sink projections

Issue #37 installs the `alerts` and `notification_sink` consumers in
`events.execution.CONSUMERS`. Both participate in the consumer execution
service's PostgreSQL transaction. The effect, receipt, attempt outcome and
delivery success commit together before the Redis reference is acknowledged.
Handlers make no external network calls.
Episode/current-state persistence belongs to `app/modules/alerts`; stub and
diagnostic persistence belongs to `app/modules/notifications`. Both use public
inventory service interfaces rather than importing inventory ORM models.

## Alert history and current state

`alert_episodes` is a derived, non-cascading projection keyed by the producer's
stable episode UUID. Opening snapshots, resolution facts, actor/order
provenance, and initialization suppression are copied from inventory's durable
`inventory_low_stock_episodes` facts. The inventory facts are authoritative and
remain available after an ingredient rename or deletion. Processing a resolution
before its opening event can therefore fill the complete history row; a later
opening delivery cannot reverse that resolution.

`alert_ingredient_states` stores one current row per ingredient and a monotonic
state revision. Before handling an inventory state event, the alerts consumer
uses the public inventory service to take the restaurant lock and load current
ingredient/balance/episode state. The projection advances to that authoritative
revision rather than applying a stale event snapshot. A subsequent stale event
may complete the episode history but cannot reopen current low state.
Low-event history processing takes the same lock, so opening and state deliveries
cannot race when inserting an episode for the first time.

`AlertProjectionService.inspect(session, organization_id, restaurant_id)` and
`rebuild(...)` are trusted transaction-bound T8 maintenance hooks, not HTTP
routes. Rebuild uses inventory's public bulk state/history interfaces and the
shared restaurant lock. It refreshes derived rows without deleting episodes,
notification outcomes, receipts, attempts, or queued events. Initialization
orchestration and operator CLI remain T8.
Inspection returns scoped `episodes` and `states` ORM rows for internal callers;
callers must serialize the selected fields and apply user authorization before
exposing them through a user-facing interface. These hooks supply no principal
or authorization bypass for HTTP requests.

## Notification stubs and diagnostic sink

`notification_stubs` holds one durable outcome per low-stock episode. Its
unique episode key applies to created stubs, stale/resolved skips, and
initialization-suppressed outcomes. For a candidate low event, the sink takes
the same restaurant lock as stock writes, loads authoritative active/low state,
and checks the current episode ID. If that episode is no longer current, it
records `skipped`; if its source facts mark an initialization baseline, it
records `suppressed`; otherwise it records `created` with immutable opening
facts. Resolution after the stub transaction commits leaves the stub intact.
No external delivery, repeat reminder, acknowledgement, or dismissal occurs.

`event_diagnostics` records order lifecycle/deletion and menu events by their
stable event UUID. It stores scope, aggregate/revision, correlation and a
small allowlisted summary of operator-useful facts; it excludes customer data,
credentials, request headers and raw exception details. PostgreSQL uniqueness
and the consumer receipt make duplicate delivery idempotent. Logs remain useful
for operations but are not the durable effect.
`notifications.service.inspect_notification_sink(session, organization_id,
restaurant_id)` supplies scoped stub/diagnostic rows for trusted operator and
maintenance integration. It is not an HTTP endpoint or external delivery API.

Additive migration `b2c7d9a41e63` creates empty tables after
`a936d8e4c021`. It seeds no derived rows. Scope foreign keys restrict restaurant
deletion; ingredient/order/event identities are retained values without cascading
business-object foreign keys. Downgrade refuses to remove any retained T7
projection or sink data. Validation targets disposable databases; the dated
[issue #37 report](../milestone8/verification-milestone8-issue37.md) records
the application-database incident separately from validation results.
