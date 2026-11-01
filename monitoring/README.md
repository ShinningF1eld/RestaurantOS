# Local monitoring foundation — issue #58

Status: Step 1 baseline declared; registry/source inspection only, runtime
acceptance pending. Recorded 2026-11-01 (Asia/Bangkok) against RestaurantOS
`50160a1a00d7261971e8fb7d72fdb8238224e7fe`.

This directory starts [issue #58](https://github.com/ShinningF1eld/RestaurantOS/issues/58),
T1 of the [current M9 observability task plan](../docs/milestone9-observability/milestone-9-observability-task.md).
It implements the foundation described by requirements R1, R2, R6 and R9 of the
[observability design](../docs/milestone9-observability/milestone-9-observability-design.md).
Historical `docs/milestone9/` deployment work belongs to current M15.

## What this step establishes

The experiment and image identities are fixed before collecting results. Later
steps will add Compose files, backend configurations, a synthetic generator,
lifecycle helpers and executable verification. There is no runnable monitoring
stack or startup command yet. No application code, dependencies, schema, database,
cloud resources or CI enforcement are changed by Step 1.

Metrics answer how much/how often, logs record individual observations, and traces
connect timed operations. The Collector receives all three; it is not their
long-term storage. Grafana queries the storage services rather than collecting
application telemetry itself.

```text
Synthetic generator -- OTLP/HTTP JSON --> Collector Contrib
                                          |-- metrics endpoint <-- Prometheus scrape
                                          |-- OTLP/HTTP logs ----> Loki
                                          `-- OTLP/HTTP traces --> Tempo
Grafana ------------------------------------> Prometheus / Loki / Tempo
```

Use five permanent services only. The temporary generator is test infrastructure,
and its resources must still be measured. Application instrumentation, live
PostgreSQL/Redis collection, four operational dashboards and alert objectives
belong to subsequent issues.

## Image selection and evidence

[images.lock.json](images.lock.json) is the authoritative image inventory. Each
reference includes a human-readable version and an immutable multi-platform index
digest. Platform manifest digests are also recorded for Linux AMD64 and ARM64.
Later Compose files must use these exact references, not floating tags or defaults
that can silently override the lock.

| Service | Selected tag | Reason |
|---|---|---|
| Prometheus | `v3.15.1` | Released 3.x patch with local TSDB time/size retention documented in the matching source. |
| Grafana | `13.3.0` | Released version with file-based data-source provisioning. |
| Loki | `3.7.9` | Released patch with native OTLP logs, filesystem storage and Compactor retention documentation. |
| Tempo | `2.10.10` | Released 2.x security patch with documented local trace storage, WAL and Compactor retention; use a single-process configuration. |
| Collector Contrib | `0.164.0` | Published upstream Contrib image with the necessary components declared in its distribution source. |

Tempo 2.x is a deliberate local-storage baseline, not a claim that it is the latest
major. Do not copy its upstream example wholesale: that example also configures
Memcached and metrics generation. Those optional paths are outside this five-service
experiment. Start with trace ingestion, querying, local persistence and retention.

The newer Contrib source release `v0.164.1` was visible, but the corresponding
Docker Hub image tag returned HTTP 404 during inspection. The published image
`0.164.0` was selected instead. Its release distribution manifest declares core
modules at `v0.164.0` and relevant Contrib modules at `v0.164.1`; the lock records
both source revisions. Verify actual binary components during the later image
smoke rather than inferring their presence from a source tag alone.

Registry inspection used anonymous Docker Registry v2 manifest reads. The
SHA-256 of each index response matched its `Docker-Content-Digest` header, and its
manifest list advertised both required platforms. No image layers were pulled
and no containers were run. Source tags were resolved to commit IDs; the lock
records immutable documentation URLs and SHA-256 hashes of reviewed bytes.
These checks establish artifact identities and source-level compatibility, not
native execution, end-to-end delivery, vulnerability clearance or resource fit.

To update a pin deliberately, review the upstream release and matching docs,
resolve its registry index, compare the response hash with the registry digest,
verify both platform manifests, and update the lock and this rationale together.
Repeat the configuration/image/signal checks after a pin changes. Do not resolve
new versions as part of ordinary validation.

## Source-level compatibility and configuration decisions

The immutable sources for this table are recorded under `sources` in the lock.

| Interface | Reviewed support | Required later implementation check |
|---|---|---|
| Generator to Collector | Core OTLP receiver supports HTTP/JSON on `/v1/metrics`, `/v1/logs`, `/v1/traces`. | Use JSON protobuf encoding, inspect partial-success responses, and validate received records. Explicitly bind the container receiver; its default is localhost. |
| Collector to Prometheus | Contrib Prometheus exporter exposes converted OTLP metrics for scraping. | Fix naming/translation and histogram units; test expected counter/histogram values and stale-source behavior. |
| Collector to Loki | Loki's native HTTP endpoint uses base path `/otlp`; its documented mapping uses structured metadata. | Enable structured metadata and use Collector exporter `otlp_http/loki`, endpoint `http://loki:3100/otlp`. Do not copy the older `otlphttp` alias from Loki's example. |
| Collector to Tempo | Tempo 2.x documents OTLP HTTP ingestion and local WAL/block storage. | Use `otlp_http/tempo` to its configured internal OTLP receiver; verify traces by ID, parentage and restart persistence. |
| Grafana to stores | Grafana supports file-based data-source provisioning. | Provision Prometheus/Loki/Tempo with stable UIDs and internal URLs; query through authenticated Grafana. |
| Collector bounds | Distribution declares memory limiter, batch/filter/transform processors and HTTP export. | Validate exact configuration syntax; bound payloads, queues, retries and shutdown, and inspect self-metrics during outages. |
| Future PostgreSQL receiver | Contrib declares the receiver; metrics are beta. Its README requires `SELECT` on `pg_stat_database` and documents separate query-sample capabilities. | #61 owns restricted grants, database scoping and measured query cost. Do not enable query-text/sample collection or assume a broad `pg_monitor` grant is required for every metric. |
| Future Redis receiver | Contrib declares the beta metrics receiver; documentation describes INFO statistics and ACL username/password support. | #61 owns exact command/ACL permissions, bounded timeout/cadence and Redis 7 runtime verification. No Redis connection is made here. |

Keep transport limited to the local private network and explicit loopback ingress.
Only Grafana and necessary host ingestion may be published; storage/query endpoints
stay internal. Proposed development Grafana port: `127.0.0.1:3001`, avoiding the
frontend's port 3000. Acceptance uses random loopback ports and unique projects.
Grafana requires authentication with ignored runtime secrets; no anonymous access.

## Declared healthy prototype workload, revision 1

This synthetic transport experiment does not measure restaurant API performance.
Its fixture latency values are manufactured observations, not measured service
latencies. Change this declaration before a revised run and retain earlier results.

| Parameter | Declared value |
|---|---|
| Workload | One generator, one fixed service name `restaurantos-monitoring-synthetic`, one operation `synthetic.operation`, outcome `success`. |
| Schedule | 5 operations/second, monotonic scheduling; no unbounded catch-up bursts. |
| Warmup | 120 seconds / 600 operations. |
| Measurement | Next 600 seconds / 3,000 operations, same process and cumulative metric start time. |
| Per operation | One trace containing two completed parent/child spans; one log correlated with the parent; one counter increment and one histogram observation. |
| Histogram | Seconds; alternate 0.010 and 0.025 seconds; explicit bounds `[0.005, 0.010, 0.025, 0.050, 0.100]` plus the implicit overflow bucket. |
| Export | One-second bounded batches for logs/traces and cumulative metric snapshots; 100% of generated traces, no incoming sampling decision. |
| Payload bounds | Log body at most 256 UTF-8 bytes; at most 8 attributes per record, string values at most 128 bytes; each serialized request at most 64 KiB. |
| Cardinality | Fixed service/operation/outcome attributes; no IDs, timestamps, run IDs, URLs or exception text in metric labels or Loki index labels. |
| Fixture identities | Deterministic unique trace/span IDs from a recorded synthetic run seed and operation sequence; keep these in trace/log metadata and the test ledger only. |
| Repetitions | One full host-ingress run and three fresh isolated container-mode runs, executed sequentially. Preserve every failed attempt and report modes separately. |
| Timing evidence | Record intended and achieved rate, phase boundaries, scheduling misses, export completion and drain time. A missed declared workload is a failed/incomplete run, not silently a smaller sample. |

The measurement phase therefore expects 3,000 logs, 3,000 traces and 6,000 spans,
a counter delta of 3,000, a histogram count delta of 3,000 and a sum delta of
52.5 seconds. Including warmup, final cumulative values are 3,600 operations/logs/
traces, 7,200 spans and a histogram sum of 63 seconds. Histogram comparisons use
a small documented floating-point tolerance; integer counts remain exact.

Do not equate export requests or Prometheus scrape samples with operation counts.
Cumulative metrics are repeatedly scraped, whereas logs and spans are individual
records. Retain a bounded fixture ledger and reconcile each model appropriately.
Keep final metrics available until the final snapshot is scraped. Record the
warmup boundary in the generator ledger; verify cumulative end values and known
phase deltas without assuming a scrape landed on the exact boundary.

The generator and Collector must acknowledge success without rejected records in
healthy runs. Confirm complete backend results within 120 seconds after the last
scheduled operation, allowing bounded drain/query time. Enumerate results beyond
API page limits and query representative trace IDs, parent relationships and log
links through Grafana as well as reconciling backend counts. Merely checking HTTP
200, a data-source health response or one visible sample is insufficient.

## Resource and acceptance rules

The combined five-container hard memory budget is **2,000,000,000 bytes** (decimal
2 GB). This definition resolves the design's otherwise ambiguous GB/GiB unit.
Step 2 must declare per-service byte limits summing to no more than that value
and verify the limits actually applied by Docker. Leave headroom for each
process inside its limit. Any reallocation is recorded; raising the total requires
an explicit proposed adjustment and preserved failing evidence.

Docker capacity of 7.49 GB is a user-reported planning input, not a newly measured
host fact. Record actual engine allocation and architecture before running. Do
not run a duplicate developer/acceptance monitoring stack during resource runs.
Report temporary generator/checker usage and overall Docker pressure separately;
they are outside the five-service sum but still consume machine resources.

| Evidence | Pass/fail rule for the later verifier |
|---|---|
| Healthy delivery | Both connection modes reconcile the declared fixture; Grafana queries show all three signals; no observed rejects/drops or unexplained missing/duplicate records. |
| Memory and restarts | Applied limits satisfy the budget; no OOM or unexplained restarts. Sample per-container memory/CPU every second, record concurrent aggregate peaks and measurement gaps. Sampled peaks are not continuous maxima. |
| CPU | Report per-service/aggregate CPU and achieved workload, with method and host CPU count. No CPU utilization ceiling or application SLO is invented here. |
| Disk | Record per-volume bytes before startup, after warmup, after measurement and after cleanup/compaction. Include WAL, indexes, chunks/blocks and bounded container logs; distinguish logical from allocated bytes. |
| Persistence | Known metrics/logs/traces remain queryable after normal down/up with volumes retained, within a declared 180-second recovery deadline. |
| Destination failure | Stop Loki and Tempo separately for 180 seconds under the same rate; inspect queue/memory/export failure evidence, unaffected signals and recovery within 120 seconds of destination readiness. Lost telemetry is permissible in the fault phase and must be reported. |
| Queue saturation | The harness must actually reach the chosen queue/retry bound. If the ordinary outage does not reach it, run a separately identified finite reduced-queue fixture; report that distinction rather than claim saturation from elapsed time. |
| Scraper failure | Stop Prometheus for 180 seconds; verify scrape gaps. Its pull path is not an OTLP exporter queue and cannot promise reconstruction of missing historical scrape samples. |
| Stale vs zero | Stop generation independently of Collector availability; distinguish an old last-observation timestamp from current healthy zero activity. Process health alone is insufficient. |
| Lifecycle cleanup | An intentional startup/mid-run failure returns nonzero and removes only owned acceptance resources; verify absence by recorded project labels. Development volumes survive normal shutdown. |
| Retention | Metrics configured for 7 days, logs/traces for 3 days; isolated accelerated fixtures prove old stored data is physically cleaned while recent controls survive. Record exact supported fixture mechanism and deadlines before execution. No host-clock changes. |
| Privacy/access | Fixed synthetic content only; authenticated Grafana, loopback ingress, no published storage ports or tracked secrets. No unrestricted debug export of telemetry. |

Fault, restart, retention and cleanup exercises are separate from healthy throughput
results. Record setup/readiness time separately (initial readiness deadline: 180
seconds), and require bounded client waits and shutdown (initial deadline: 30
seconds). Missing readiness, cleanup, collection or reconciliation evidence is a
failure or an explicit unverified criterion, never a successful zero.

Retention configuration is not a disk byte ceiling. The later prototype report
must propose an initial disk budget from measured per-service growth plus startup,
WAL and compaction headroom. A short experiment cannot prove seven days of capacity;
state extrapolation uncertainty and any earlier size-based eviction or shortened
retention. No disk budget or resource-fit result has been measured in Step 1.

## Remaining evidence and handoff

Normal-development sampling proposal: start with a parent-based 10% root sampling
ratio in later application instrumentation, with runtime verification and tuning
deferred to those issues. This is a proposal, not an implemented policy. The
synthetic acceptance generator always emits 100% of its declared spans; do not
let inherited sampling flags reduce acceptance counts.

Step 1 is complete when the lock parses, all five image/index identities match
the inspected registry responses, both required platform descriptors exist,
reviewed source references are immutable, and workload arithmetic is consistent.
Those checks do not satisfy issue #58's runtime acceptance criteria.

Next, implement Compose/network/storage/resource wiring from this inventory.
Later evidence must retain exact commands, source/config hashes, image IDs,
architecture/native-or-emulated status, workload settings, sanitized results,
loss/restarts, failures and owned-resource cleanup. Keep final issue acceptance
open until both modes, retention, outages, persistence and resource measurements
have actually passed. No application migration or hosted readiness is involved.
