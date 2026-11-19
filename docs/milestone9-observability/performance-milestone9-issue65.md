# Issue #65 local application baseline

T8 baseline evidence and the local numeric objectives are **accepted**. The
user approved the objectives and alert evaluation settings below on 2026-11-19.
T9 owns rule implementation and incident verification.
Sources are [issue #65](https://github.com/ShinningF1eld/RestaurantOS/issues/65),
the [M9 design](milestone-9-observability-design.md#alerts-service-objectives-and-response)
and the [declared experiment](experiment-milestone9-issue65.md).

## Controls and interpretation

The two arms use the same application images, pool settings and HTTP workload.
The enabled arm starts the five additional monitoring containers, with the API,
worker and Next.js samplers set to always-on. This measures the combined cost of
instrumentation and its local ingestion stack. Both arms use direct PostgreSQL
and Redis observations in place of the optional native Collector receivers.
These observations cover PostgreSQL connection activity, durable delivery counts
and Redis stream lengths.

The client clock times whole HTTP responses in milliseconds. The latency table
uses successful responses for each normalized operation and treats the expected
409 replay separately. The observed unexpected-error denominator is all
measured client attempts other than the deliberate conflicts. The alert's API
denominator is instrumented API requests, including internal calls from SSR
and using API outcomes to separate expected 4xx. The client also counts transport
and invalid rendered responses, which the API metric cannot observe. Server
Prometheus histogram buckets use seconds. Convert to milliseconds for display.

Freshness uses the difference between the PostgreSQL commit timestamp of the
outbox insert and that of the consumer receipt. Both come from the same server
clock. Processed receipts commit in the same transaction as the consumer effect.
Skipped receipts still measure durable handling and carry their separate outcome
in the raw data. Queue sampling captures status and age at observation time.
Prometheus backlog age is a sampled oldest-item gauge, distinct from the
completed-effect freshness distribution.

The initial short wiring run exposed a runner assertion that searched the menu
index for an item name. It also expected zero charged attempts on successful
deliveries, when success takes one attempt. The workflow still completed all
three orders, and all 32 deliveries succeeded. The run used a Windows clock that
quantized short request timings. The full matrix checks the rendered menu name,
expects one attempt without retries, and uses the high-resolution performance
counter. The [failed smoke report](evidence/issue65-smoke-01.json.gz) is retained
outside the comparison.

## Retained run and environment

The full matrix started on 2026-11-19 at 19:47 ICT from RestaurantOS
`bb01d8cd8e0d8a869538f69cdec5f09acbc7967e`. Its [sanitized raw report](evidence/issue65-baseline.json.gz)
records the exact dirty-worktree harness and configuration hashes, running image
IDs, per-request results, PostgreSQL effect records, resource samples and
telemetry series for each arm. The migrations resolved to `d4e9f2a63b85` in the
disposable databases. The Windows 11 host used Python 3.12.13, 12 logical CPUs
and 16.98 GB physical memory. Docker Engine 29.6.2 and Compose 5.3.1 ran Linux
amd64 containers with 12 CPUs and 8.23 GB of reported memory. The original 7.49 GB
design limit remains the more conservative comparison boundary.

Both arms used PostgreSQL 16.15 (`16.15-1.pgdg13+2`), Redis 7.4.11 and the same
production API/worker and Next.js 16.3.7 standalone builds. The enabled arms used
Collector Contrib 0.164.0, Prometheus 3.15.1, Grafana 13.3.0, Loki 3.7.9 and Tempo
2.10.10. Match the resolved image IDs and source hashes in the raw report for an
exact repeat. The shared test Compose PostgreSQL and Redis tags can resolve to
different images over time.

## Workload results

All six repetitions passed. Each measured phase recorded 306 successes, 18
expected 409 conflicts and zero unexpected results. That gives **0/1,836**
unexpected results across eligible attempts and **108** separate conflicts.
The warmup included a cold Next.js render that delayed some reads by up to
1.67 seconds. During measurement the worst delayed read start was 9 ms and the
worst delayed workflow start was 2 ms. Every scheduled attempt ran.

Each arm, including warmup, reconciled 24 completed orders and 300.00 THB in the
daily projection, 24 stock receipts, 24 consumption movements and a one-piece
final balance. There were 24 order-triggered alert openings and 25 notification
stubs, including the opening-stock episode. All 200 required deliveries per arm
succeeded on one charged attempt. The matrix had no failed repetitions.

### HTTP latency and instrumentation overhead

Nearest-rank P95 in **milliseconds** for the 90-second measurement window. The
paired columns show off → on, even though pair 2 ran on first. Reads have 36
observations per arm and each command step has 18. At 18 observations P95 equals
the maximum. P50, P99 and per-attempt results are in the raw report.

| Operation | Pair 1 off → on | Pair 2 off → on | Pair 3 off → on | Median paired change, ms |
| --- | ---: | ---: | ---: | ---: |
| List menus | 24.3 → 23.5 | 17.8 → 21.3 | 21.1 → 28.1 | +3.6 |
| List menu items | 23.6 → 29.2 | 17.9 → 24.9 | 19.4 → 23.6 | +5.6 |
| List inventory ingredients | 19.9 → 28.7 | 16.3 → 23.7 | 15.4 → 25.0 | +8.9 |
| Read analytics dashboard | 25.8 → 29.0 | 21.2 → 28.1 | 22.5 → 20.7 | +3.2 |
| Render authenticated menus page | 44.4 → 39.1 | 51.5 → 41.6 | 43.4 → 50.6 | −5.3 |
| Receive stock | 34.1 → 39.9 | 32.7 → 37.7 | 34.5 → 40.0 | +5.5 |
| Create draft order | 31.7 → 23.9 | 22.4 → 24.7 | 20.5 → 27.0 | +2.3 |
| Submit order | 38.1 → 26.8 | 23.0 → 22.2 | 23.1 → 24.3 | −0.9 |
| Accept order | 64.2 → 35.2 | 29.3 → 32.9 | 32.4 → 36.6 | +3.6 |
| Start preparation | 21.5 → 19.3 | 15.1 → 19.6 | 20.3 → 22.5 | +2.2 |
| Mark order ready | 17.7 → 20.7 | 22.0 → 18.9 | 18.2 → 26.4 | +2.9 |
| Complete order | 28.8 → 32.3 | 18.9 → 30.7 | 20.3 → 22.9 | +3.5 |
| Mismatched draft replay, expected 409 | 13.8 → 13.0 | 14.6 → 12.3 | 12.2 → 17.4 | −0.8 |

Item and inventory reads were slower in all three enabled arms. Other routes,
including SSR and order acceptance, varied by pair. The comparison describes
observed end-to-end cost on this host at 3.6 scheduled client attempts per second.

### Effect freshness, connection pools and backlog

P95 and maximum are **seconds** from the source commit to the effect commit.
Each mode pools its three measured phases here. Each arm also recorded 18
skipped alert receipts, retained separately in the raw data.

| Consumer | Processed per mode | Off P95 / max | On P95 / max |
| --- | ---: | ---: | ---: |
| Analytics | 54 | 1.504 / 1.545 | 1.396 / 1.539 |
| Alerts | 108 | 1.484 / 1.589 | 1.433 / 1.611 |
| Notification sink | 216 | 1.539 / 1.641 | 1.450 / 1.639 |

PostgreSQL activity samples showed at most 10 open application connections and
zero sampled lock waits. At most eight deliveries were pending or in progress,
and the oldest such sampled delivery was 1.516 s (rounded up). The 15-second
worker telemetry snapshots showed zero oldest unfinished age in all enabled
arms. The difference reflects brief backlog between those snapshots. Redis
retained 200 stream entries at peak, including acknowledged entries.
Prometheus samples saw up to 1 of 15 API and 2 of 6 worker pool slots in use.
Pool acquisition-failure series did not appear and no timeouts surfaced in the
client workload. Pool usage and in-progress acquisition are sampled signals.

### CPU, memory, disk and telemetry volume

Docker memory is cache-adjusted working set. Aggregate peaks sum the services
in each sample before taking the maximum. VM pressure is `MemTotal − MemAvailable`
from `/proc/meminfo` and includes the services and VM overhead. CPU is the mean
of the measurement-period samples, where 100% means one logical CPU.

| Arm | Peak app/DB/Redis, MB | Peak five monitoring services, MB | Peak all containers, MB | Peak VM used, MB | Mean container CPU |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 off | 419 | — | 419 | 1,584 | 18.7% |
| 2 on | 390 | 766 | 1,155 | 2,070 | 31.7% |
| 3 on | 391 | 553 | 944 | 2,071 | 24.4% |
| 4 off | 405 | — | 405 | 1,593 | 18.3% |
| 5 off | 421 | — | 421 | 1,550 | 18.9% |
| 6 on | 387 | 555 | 941 | 2,086 | 28.2% |

The enabled median added 9.4 percentage points of one CPU core. The highest
enabled per-service working sets were Collector 86 MB, Prometheus 58 MB,
Grafana 516 MB, Loki 79 MB and Tempo 50 MB. The enabled combined peak was
**0.766 GB against the 2 GB cap**. The VM used **2.086 GB against the 7.49 GB
design limit** and had at least 6.144 GB available of its actual allocation.
The host-side driver peaked at 103 MB of working set over the process lifetime
and used 1.4–4.1 CPU seconds per arm. Volume observations used one bounded
128 MB helper at a time around the workload. Even adding that full limit to the
observed VM peak leaves over 5 GB below the 7.49 GB boundary. Samples showed
zero VM swap use and container inspection showed zero OOM kills or restarts.
The existing memory split fits this workload.

Monitoring volumes grew by 1.99–2.05 MB allocated per enabled arm after fixture
setup. The largest contributions were Tempo (1.17–1.21 MB), Prometheus
(0.63–0.64 MB) and Loki (0.20–0.21 MB). Grafana's allocated data size held steady.
The temporary PostgreSQL data directory ended near 52 MiB and application
writable layers held at 4 KiB each. Docker's backing filesystem reported about
1.01 TB of virtual free space. These short runs measure initial growth and leave
retention-period disk demand and physical host disk headroom unmeasured.

| Enabled arm | Spans accepted / sent to Tempo | Logs accepted / sent to Loki | Metric points accepted / sent to Prometheus | Peak Prometheus head series |
| --- | ---: | ---: | ---: | ---: |
| 2 | 1,681 / 1,681 | 543 / 543 | 5,729 / 5,729 | 4,627 |
| 3 | 1,681 / 1,681 | 543 / 543 | 5,443 / 5,443 | 4,596 |
| 6 | 1,681 / 1,681 | 543 / 543 | 5,540 / 5,540 | 4,644 |

These are whole-arm Collector cumulative observations, including setup,
warmup, measurement and export drain, and count signal records rather than
business requests. Receiver refusals were zero. Exporter failure and enqueue
failure counters were absent, observed queue occupancy was zero at scrape
times, and the SDK warning scan found zero matching lines. Each trace sampler
was always-on. Collector counts measure arrival and exporter acknowledgements.
SDK loss before arrival and queue peaks between scrapes are outside those counts.

## Accepted local objectives

Evaluate these against the declared healthy workload with telemetry enabled. The
thresholds apply to this synthetic traffic rate and dataset.
Evaluate each operation independently and each enabled repetition independently.
Require at least the declared 36 observations per read/SSR route and 18 per
successful command. For the full-HTTP objective, use nearest-rank percentiles.

| Objective | Accepted value | Basis |
| --- | --- | --- |
| Direct API read latency | P95 at most 100 ms per read operation | Leaves margin above the worst enabled read P95 of 29.2 ms. |
| API command latency | P95 at most 150 ms per successful command | The worst enabled command P95 was 40.0 ms. The paired acceptance P95 varied by up to 29.0 ms. |
| Authenticated menu SSR latency | P95 at most 200 ms | The worst enabled warm P95 was 50.6 ms for rendering, internal API reads and full HTML. The cold render is measured in warmup. |
| Unexpected client errors | Below 1% of eligible measured attempts per repetition | The enabled arms observed 0/918, with 54 expected conflicts tracked separately. Includes transport and render failures. |
| Committed consumer effects | P95 at most 3 s per consumer and every processed effect at most 5 s | Enabled pooled P95s were at most 1.451 s and the slowest effect was 1.639 s. Reconcile every delivery by the drain deadline. |

## Accepted alert settings for T9

Evaluate every **15 seconds**. All sustained and recovery intervals require
consecutive eligible evaluations. Group API errors for the stack, DB saturation
by runtime role and worker slot, and work alerts by consumer. Monitor missing
telemetry separately. Unsupported or stale inputs stay unknown and cannot cause
a fresh firing or mark an existing incident resolved. A healthy scrape and a
fresh source are required. Use the API last-observation freshness (45 s), healthy
pool gauges exported within their normal expiry, and the worker's last successful
collection age (45 s). Treat observed zero and insufficient traffic separately.

| Alert | Evaluation and minimum signal | Fire when sustained | Resolve when sustained | Reason |
| --- | --- | --- | --- | --- |
| API unexpected errors | Five-minute increase in `server_error` divided by the increase in `success + server_error` for API routes other than `/health` and `/ready`. Require at least 60 eligible requests. Track expected 4xx and cancellations separately. | Greater than 2% for 2 min | Below 1% for 2 min with the same traffic minimum | The workload supplies enough eligible traffic and the injected 409s remain outside the numerator and denominator. At the minimum, two errors are needed to cross the ratio. |
| Database pool saturation | Per API or worker pool, evaluate `pool_used / pool_limit` on fresh paired gauges. For utilization require at least 20 acquisitions in 2 min. An acquisition timeout can signal pressure even at low traffic. | At least 80% used or at least one acquisition timeout in 2 min, for 1 min | Below 60% used and no timeout in the previous 2 min, for 2 min with fresh gauges | Both pools have numeric capacity and a timeout is direct evidence of acquisition pressure. Instantaneous utilization can miss short waits. |
| Old unfinished work | Per consumer, oldest age over queued, in-flight, retry-delayed and recovery-due deliveries. Require at least one unfinished delivery to breach. | Older than 10 s for 1 min | Oldest below 5 s or fresh zero depth, for 1 min | The age threshold gives ordinary relay cycles headroom. Sustaining it across four worker sample intervals filters transient queueing. |
| Repeated job failures | Per consumer, count retry-scheduled outcomes over 5 min or read durable terminal depth. Minimum is three retry observations or one terminal delivery. | At least three scheduled retries or at least one terminal delivery, for 1 min | Fewer than three scheduled retries in 5 min and fresh zero terminal depth, for 2 min | Healthy completions require one charged attempt and no retry. A terminal delivery needs review even when new traffic is sparse. |

For retry and timeout counts, T9 needs to demonstrate first-failure and counter
reset behavior as well as recovery after a telemetry gap. Process counters can
miss pre-scrape observations. The retry rule uses the bounded consumer label.
Inspect durable deliveries and traces
to identify the jobs involved. An expired or missing worker snapshot stays
unknown even if the process retry counter is idle.

## Reproduction and approval record

See the [commands and report schema](../testing/monitoring.md#paired-local-application-baseline-65).
The baseline workload is opt-in and migrates only a newly allocated `_test`
database. The implementation is limited to the harness and its evidence and
documentation. Both production image builds succeeded. The six-arm command was:

```powershell
backend/.venv-observability/Scripts/python.exe scripts/benchmark-local-observability.py --report docs/milestone9-observability/evidence/issue65-baseline.json.gz
```

The focused repository gates passed with all 529 backend unit tests and one
existing Starlette deprecation warning:

```powershell
backend/.venv-observability/Scripts/python.exe scripts/validate.py --gate baseline --gate backend-static --gate backend-unit --no-install
git diff --check
```

The archive's source hashes, counts and proposed-objective calculations were
checked against the raw records. Docker inspection confirmed cleanup of the
benchmark's containers, networks and volumes. The full M9 gate set and T9
incident and recovery exercises remain separate milestone evidence.

| Decision | Status |
| --- | --- |
| Accept the local objectives and alert settings above for T9 | Approved |
| Approver, date and decision reference | User, 2026-11-19 (ICT), selected “Approve objectives and alert settings” in the Issue #65 implementation chat. |
