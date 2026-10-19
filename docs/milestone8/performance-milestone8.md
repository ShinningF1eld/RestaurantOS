# Milestone 8 processing freshness and operational evidence

Measured: 2026-10-19 (Asia/Bangkok). Authoritative scope:
[approved M8 design revision 1](milestone-8-design.md), requirements R3/R6/R11–R14
and [issue #41](https://github.com/ShinningF1eld/RestaurantOS/issues/41).
Code base: `88eee5483838f531e446969e731a34d2dcbeee29`, with uncommitted T11
harness/unit/static-check/documentation additions. Production worker/handler
source is unchanged from that base. Each retained JSON includes the exact
measurement script SHA256; no commit or push was performed.

## Workload, environment and method

The [reproduction procedure](../testing/event-freshness-benchmark.md) specifies
the commands, exact eight-event mix, fixture limitations, commit intervals,
nearest-rank calculation and teardown. One branch, one UTC date, 40 low
ingredients and completed orders per run: 320 events and 440 subscribed effects
(80 analytics, 80 alerts, 280 sink). Every event is measured. Six order/menu events
per bundle are synthetic committed fact fixtures; inventory creation uses the
real authorized service. This measures delivery/projection freshness, not HTTP
throughput or end-to-end order lifecycle latency.

Windows / Intel Core i5-12400F (12 logical processors, 15.82 GiB host RAM), Python 3.12.13, Node
24.14.1/npm 11.11.0, Docker Engine 29.6.2 / Compose 5.3.1; committed dependency
locks. PostgreSQL/Redis versions and all worker settings are in each JSON.
Docker reports 12 CPUs and 8,227,790,848 bytes available memory.
PostgreSQL 16 and Redis 7 run in separate owned Compose containers with random
loopback ports; the single production worker and measurement process run on the
host. Repository migration head and each disposable database are at
`c3d8e1f52a74`. The application database is not a benchmark target and its actual
revision/cutover was not inspected or changed.

Default worker tuning is unchanged: 10 delivery claims/batch, two relay
publications at once, 1,500 ms scans, 10 group/recovery reads per pass, 30-second
claims, 60-second stalled publication/reclaim, 2,000 ms Redis deadline/1,000 ms
blocking read, eight event-specific attempts and ten-second shutdown grace.
The worker sleeps after each relay batch, so 10/1.5 = 6.67 delivery publications/s
is an optimistic bound before database/Redis processing costs. Fan-out can create
duplicate transport references even though effects remain unique. Do not infer
production capacity from this arithmetic or the small dataset.

Healthy cells schedule 0.5 bundles/s (four events/5.5 subscribed deliveries/s),
with up to four producers. The pressure cell schedules two bundles/s (16
events/22 subscribed deliveries/s). Runs are serial, after the full validation,
with no validation/build process competing with the measurement. The concurrent
producer limit is an upper bound; the paced workload may use fewer slots.

After real misses appeared in the original paced runs, an additional light cell
was selected: 20 bundles at 0.25/s (two events/2.75 deliveries/s), with the same
worker tuning and producer limit. It is reported separately, retaining all
original repetitions. "Healthy" filenames mean dependencies were available;
they do not assert target compliance. There is no earlier comparable M8 baseline,
so no latency improvement or regression against an earlier implementation is
claimed. The observer's repeated SQL scans add load to this local measurement.

Latency tables use conservative monotonic upper bounds from immediately before
producer COMMIT to first independently visible committed receipt. Lower bounds
exclude producer acknowledgement and observation uncertainty. A lower bound
over five seconds is a proven miss; an upper bound alone over five seconds can
be measurement uncertainty. Raw per-delivery bounds, bracket widths and backlog
samples remain retained. No transaction timestamp is treated as commit time.

## Measured results

All five cells returned 0 with `correct:true`. Every measured subscribed effect
completed once: **1,440 events / 1,980 receipts**, with no missing effects,
charged retries or failed deliveries. **The five-second target was not
consistently met at any tested load.** P95 was below five seconds in the light
cell, but it still had two proven 61-64 second misses. The original paced cells
have 1,125 proven misses out of 1,320 deliveries; the pressure cell has 419/440.
No outage was injected during any latency cell.

Latency values below are **seconds**, nearest-rank upper bounds. `Proven`
uses lower bounds above five seconds; `Upper` includes uncertain crossings.

| Cell | Consumer | N | P50 | P95 | P99 | Maximum | Proven misses | Upper exceedances |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| paced-1 | analytics | 80 | 10.465 | 17.351 | 18.247 | 18.247 | 66 | 66 |
| paced-1 | alerts | 80 | 11.511 | 19.443 | 19.921 | 19.921 | 72 | 73 |
| paced-1 | notification_sink | 280 | 11.287 | 18.264 | 19.638 | 19.773 | 242 | 244 |
| paced-2 | analytics | 80 | 8.424 | 14.623 | 15.470 | 15.470 | 65 | 65 |
| paced-2 | alerts | 80 | 10.420 | 16.531 | 16.896 | 16.896 | 67 | 68 |
| paced-2 | notification_sink | 280 | 9.576 | 15.874 | 17.045 | 72.454 | 239 | 242 |
| paced-3 | analytics | 80 | 9.471 | 15.745 | 17.948 | 17.948 | 64 | 66 |
| paced-3 | alerts | 80 | 11.232 | 17.733 | 18.400 | 18.400 | 72 | 73 |
| paced-3 | notification_sink | 280 | 10.304 | 16.879 | 18.255 | 73.511 | 238 | 240 |
| pressure | analytics | 80 | 35.342 | 68.048 | 72.136 | 72.136 | 76 | 76 |
| pressure | alerts | 80 | 37.117 | 68.786 | 72.595 | 72.595 | 76 | 76 |
| pressure | notification_sink | 280 | 36.967 | 69.052 | 72.861 | 121.475 | 267 | 269 |
| light | analytics | 40 | 1.919 | 2.689 | 3.040 | 3.040 | 0 | 0 |
| light | alerts | 40 | 2.592 | 4.023 | 63.967 | 63.967 | 1 | 1 |
| light | notification_sink | 140 | 2.482 | 3.489 | 3.719 | 61.663 | 1 | 1 |

Pooled original paced repetitions (0.5 bundles/s, all 1,320 samples):

| Consumer | N | P50 | P95 | P99 | Maximum | Proven / upper misses |
|---|---:|---:|---:|---:|---:|---:|
| analytics | 240 | 9.315 | 16.268 | 17.869 | 18.247 | 195 / 197 |
| alerts | 240 | 11.103 | 18.168 | 19.611 | 19.921 | 211 / 214 |
| notification_sink | 840 | 10.322 | 17.352 | 19.280 | 73.511 | 719 / 726 |

Per-repetition P95 varies: analytics 14.623-17.351 seconds, alerts
16.531-19.443 and sink 15.874-18.264. Pooling does not remove that variation.
Small per-consumer sample sizes also matter: nearest-rank P99 of 40 samples
is their maximum; the 140-sample light sink P99 omits its single long tail.

Backlog/age are sampled PostgreSQL unfinished work, not stream length. Drain
is elapsed observation time from the first scheduled bundle through the final
receipt. Peak values can occur at different observations.

| Cell | Peak depth | Peak oldest age (s) | Drain (s) | Retained stream entries |
|---|---:|---:|---:|---:|
| paced-1 | 91 | 19.869 | 98.209 | 415 |
| paced-2 | 81 | 72.445 | 120.576 | 405 |
| paced-3 | 89 | 73.494 | 123.634 | 407 |
| pressure | 353 | 121.452 | 138.041 | 410 |
| light | 13 | 63.967 | 121.788 | 211 |

After drain, every consumer has pending=0, oldest age=null, retries=0 and
failed=0. Full cells retain 80/80/280 deliveries, receipts and attempts for
analytics/alerts/sink; light retains 40/40/140. These are charged processing
attempts, not Redis publication/redelivery counts. Stream size is retained
transport and may include duplicate references or be smaller than fan-out.

Database counts captured **before maintenance and the separate fault rehearsal**:

| Table | Each full cell | Light cell |
|---|---:|---:|
| `outbox_events` | 320 | 160 |
| `event_deliveries` | 440 | 220 |
| `event_receipts` | 440 | 220 |
| `event_delivery_attempts` | 440 | 220 |
| `event_delivery_replays` | 0 | 0 |
| `analytics_order_contributions` | 80 | 40 |
| `analytics_daily_sales` | 1 | 1 |
| `alert_episodes` | 40 | 20 |
| `alert_ingredient_states` | 40 | 20 |
| `notification_stubs` | 40 | 20 |
| `event_diagnostics` | 240 | 120 |

Each full cell reconciles 40 completed orders / 500.00 sales, 40 current low
episodes, 40 created stubs and 240 diagnostics; light has 20 / 250.00, 20,
20 and 120 respectively. All receipts have `processed` outcomes; no workload
event is intentionally stale. Graceful worker exit is zero in all cells.
Both pre/post-maintenance SQL reconciliations match, initialization rerun
returns the original operation ID, and rebuild succeeds.

Measured source: script version `1.0.0`, SHA256 `e7b17362e66e8a2a1ea9c3997f2f208ec8a313b5751f04daf04386b8912f513a`.
Every cell records PostgreSQL 16.15 and Redis 7.4.11. Raw per-delivery bounds
and backlog observations are retained in [paced-1.json](benchmarks/paced-1.json), [paced-2.json](benchmarks/paced-2.json), [paced-3.json](benchmarks/paced-3.json), [pressure.json](benchmarks/pressure.json), [light.json](benchmarks/light.json).

The [safe correlated paced-2 tail](benchmarks/paced-2-tail.json) shows a
`delivery_missing_or_busy` reference followed by publication/processing about
61 seconds later. Its true latency is bounded at 72.336-72.454 seconds.
This is consistent with the unchanged 60-second pending/stall recovery
budgets; the trace does not identify the exact competing lock holder.
The light cell also has 61.663-second sink and 63.967-second alert maxima;
the pressure sink reaches 121.475 seconds. Reported maxima and misses must
accompany the percentiles. Queue growth plus delayed busy-reference recovery
is an operational limitation even with healthy dependencies. A separate
performance change must validate capacity and earlier bounded busy-reference
revisits before relying on the target. This evidence task changes no tuning.

## Operational evidence and limits

The healthy run with `--operations` retains actual CLI status/inspect/replay JSON
and original event, consumer, correlation, delivery, replay and maintenance IDs.
Its test-only constraint-failing sink is replaced by the production handler;
analytics succeeds independently once. The queued-work worker is forcibly killed,
only the owned stream is removed, and a new production worker recovers with the
same PostgreSQL identity. Precise in-flight death and physical Redis restart are
separately covered by the required full integration gate, not inferred from this
startup/queued-work rehearsal.

Every measurement stops writers/the worker before actual CLI initialization,
rerun, rebuild and SQL reconciliation. Rerun preserves initialization identity;
receipts and queued facts are retained. Backup/restore and baseline suppression
are covered by the full migration/integration gates. Application cutover remains
an explicit operation under the [maintenance runbook](../runbooks/event-maintenance.md).

The UI refreshes every 15 seconds while visible; that is separate from the
five-second healthy processing target and can add visible delay. No outage-time
completion bound is claimed. No event/history/receipt or Stream pruning exists;
storage growth is retained and visible, not a production retention commitment.
The dashboard stays on live SQL. External notifications, M9 deployment, M10 full
tracing and M11 broader analytics/timezones remain deferred. See the
[acceptance review](verification-milestone8-issue41.md) for local gates, the
R1–R14/roadmap evidence map and the untested final PR CI boundary.
