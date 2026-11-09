# Operator business metrics

Issue #63 adds metrics to the optional API OpenTelemetry runtime. The Collector
admits them from `restaurantos-api`, strips unapproved attributes and exports
them through the existing internal Prometheus target. Grafana reads through its
authenticated Prometheus data source. The API exposes no aggregate or metrics
route. Existing restaurant analytics and inventory alert APIs keep their normal
authorization and scope checks.

## Enable collection

Set `MONITORING_ENABLED=true` to observe command activity. For deployment-wide
aggregate gauges also set `MONITORING_BUSINESS_AGGREGATES_ENABLED=true` on one API
process per monitored stack. Use the local operator stack and trusted OTLP
endpoint described in the [monitoring runbook](../runbooks/monitoring.md). Keep
the Collector's OTLP ingress loopback-only or on the private service network
and its Prometheus endpoint internal. The service name is a filter, so the
network boundary and operator access controls provide isolation. Do not combine
independent deployments under the same Collector series. The existing API
resource has one identity per stack, including for process-local counters.

`MONITORING_BUSINESS_COLLECTION_SECONDS` defaults to 30 (range 15–300). The
sampler runs immediately, then waits that interval between attempts. The API
opens at most one separate PostgreSQL connection per sampler, using its
configured database identity in a read-only repeatable-read transaction.
Each SQL statement has a one-second timeout and each collection has a
three-second application deadline. There are no reads on OTLP collection or
Prometheus scrape. With aggregate sampling disabled there is no sampler or
aggregate connection. No monitoring backend receives database credentials.

## Metric contract

All OTLP names below start with `restaurantos.business.`. All Prometheus names
start with `restaurantos_business_`. The Collector derives constant
`job="restaurantos-api"` and `service_name="restaurantos-api"` labels.
Prometheus stores its configured scrape job as `job="collector-telemetry"`
and keeps the ingested job label as `exported_job`.
There are no tenant, restaurant, user, order, event, delivery, idempotency
or payload dimensions.

| OTLP suffix | Prometheus suffix | Type and unit | Meaning and dimensions |
| --- | --- | --- | --- |
| `orders.transitions` | `orders_transitions_total` | Counter, transitions | API-observed commits. `transition` is `SUBMITTED`, `COMPLETED` or `CANCELLED`. Draft creation, repeated states and failed transactions contribute nothing. |
| `stock.rejections` | `stock_rejections_total` | Counter, attempts | Stock-related rejected commands. `category` is one of the seven values below. |
| `stock.episode_openings_24h` | `stock_episode_openings_24h` | Gauge, episodes | Durable producer openings over the preceding 24 hours `[as_of - 24h, as_of)` for extant restaurant scopes. `kind` is `operational` or `baseline`. Resolved episodes remain in their original opening window. |
| `stock.active_ingredients` | `stock_active_ingredients` | Gauge, ingredients | Live active ingredients with balance at or below reorder threshold, including legacy low stock awaiting episode initialization. |
| `stock.active_alerts` | `stock_active_alerts` | Gauge, alerts | Projected alert openings that still match the live producer episode and low condition. An opening may be absent while the alert worker catches up. A stale projected opening stops counting once stock recovers. |
| `sales.retained_orders_7d` | `sales_retained_orders_7d` | Gauge, orders | Retained projected completed orders over the seven UTC creation dates below. |
| `sales.retained_amount_7d` | `sales_retained_amount_7d_THB` | Gauge, THB | Corresponding retained completed-order amount, opt-in. |
| `analytics.deliveries` | `analytics_deliveries` | Gauge, deliveries | Durable analytics work count by `state`. |
| `analytics.oldest` | `analytics_oldest_seconds` | Gauge, seconds | Age of the oldest delivery by `state` at the snapshot, measured from its durable delivery creation time. Zero for an empty state. |
| `collection.last_success` | `collection_last_success_seconds` | Gauge, Unix seconds | Source transaction timestamp of the last successful snapshot. Absent before the first success. |
| `collection.success` | `collection_success` | Gauge, 0 or 1 | One after successful collection, zero before the first successful snapshot or after a failed attempt. |
| `collection.freshness_budget` | `collection_freshness_budget_seconds` | Gauge, seconds | Maximum accepted source age. Twice the configured collection interval plus the SDK export interval and ten seconds for Collector batching and Prometheus scraping. Emitted when aggregate collection is enabled. |

Stock rejection categories are `order_item_unavailable`, `order_recipe_invalid`,
`order_stock_insufficient`, `inventory_inactive`, `inventory_count_stale`,
`inventory_stock_insufficient` and `inventory_balance_limit`. Requests rejected
before reaching these rules, such as failed authorization, malformed input or
an idempotency-key mismatch, have their existing HTTP outcomes. A repeated
stock conflict counts as another attempt. Only committed inventory changes or
maintenance initialization create durable episodes. Initialization baselines
retain their notification suppression and are shown separately from new
operational openings.

The two counters are process-local and best-effort. The API increments order
transitions after the PostgreSQL commit and records rejection attempts at the
existing stock rules. The SDK exports on its own threads. Crashes, exporter
failures and restarts can lose observations or reset counters. For durable
history use the existing audit, inventory episode and analytics data.

## Sales period and precision

The window is `[00:00 UTC six calendar dates before the snapshot date, 00:00 UTC
on the following date)`. It includes the current, possibly partial UTC date.
`analytics_daily_sales` groups by **order creation date in UTC**. A recent
completion of an order created before the window is outside it. A permitted
deletion can decrease the gauges after the deletion event is applied. Existing
receipts, revisions and deletion tombstones govern the projection.

PostgreSQL `NUMERIC` and Python `Decimal` remain authoritative. The application
stores no per-order currency and its existing UI displays THB. Set
`MONITORING_BUSINESS_SALES_THB=true` only after verifying all retained prices in
the monitored database are THB. If the currency is unknown or inconsistent,
leave it disabled. The sampler then queries counts without summing amounts and
the amount series is absent. The conversion to binary float takes place at
the SDK boundary and Prometheus can round values, particularly cents at large
totals. These gauges support operational visualization. They carry no financial
accounting, revenue-recognition or audited-reporting guarantees.

## Freshness and query bounds

Gate aggregate panels on a successful scrape, `collection_success == 1`, and
a nonnegative source age below `collection_freshness_budget_seconds`. The budget
is 75 seconds at the default 30-second collection and five-second export
intervals. Grafana reads the reported budget for each sample. Treat missing,
future, expired or failed collection as unknown. Historical samples and older
API/Collector versions without the budget remain unavailable in aggregate
panels. The source age remains visible when present.

A failed read leaves the previous snapshot timestamp intact. The Collector
and Prometheus can continue to serve prior gauge values while the sampler or
export is stopped. A successful scrape or SDK export cannot advance the source
timestamp. The existing Prometheus `up{job="collector-telemetry"}` series
separately indicates scrape availability.

Separately show the analytics delivery states `queued`, `retry_delayed`,
`in_flight`, `recovery_due` and `terminal`. Any positive count shows durable
analytics work requiring processing, recovery or operator review. The age
increases across valid samples as work waits, even without an active worker.
These diagnostics cover all retained analytics deliveries, including work
outside the sales window. Zero across states means no recorded outstanding
deliveries at that snapshot. It cannot establish legacy initialization,
projection integrity, or effects of events committed since the snapshot.
Use the existing scoped [analytics reconciliation](analytics-projection.md)
for data discrepancies. Show projected sales as such even with an empty backlog.

Sampling uses fixed-result, feature-owned aggregate statements. Recent sales
and openings use the existing branch/date and scope/opened-at indexes.
Current stock reads live inventory rows. Current alerts are fenced by the
unresolved producer rows and their projected episode IDs. Backlog reuses the
worker diagnostics classification and unfinished/failed index, with an
analytics consumer filter. Work can grow with restaurant count, live catalog
size, recent episode volume and unresolved or terminal deliveries. Timeouts
turn overload into an unknown sample. The sampler does not scan order
contributions, replay event payloads, or traverse completed delivery history.
