# Issue #58 original experiment declaration

Originally declared before measurement in `monitoring/README.md` at `394ac80`.
Preserved here when that guide was consolidated into current setup instructions.
The snapshot includes clarifications from later implementation checkpoints,
all made before timed measurement.
These are the original expectations, not a claim that every detail was executed
exactly. [The final verification](verification-milestone9-issue58.md) records
actual commands, sampling cadence, the shorter first scraper fixture and other
limitations. [The resource report](performance-milestone9-issue58.md) contains
the four fixed healthy trials. Initial image compatibility analysis remains in
`monitoring/images.lock.json` and dated Step 3 verification.

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
Step 2 declares per-service byte limits summing to that value. Verify the limits
actually applied by Docker during the first running-stack check. Leave headroom for each
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

Compose wiring and service pipelines are present; next implement Step 4's Grafana
data-source provisioning and verify authenticated operator access.
Later evidence must retain exact commands, source/config hashes, image IDs,
architecture/native-or-emulated status, workload settings, sanitized results,
loss/restarts, failures and owned-resource cleanup. Keep final issue acceptance
open until both modes, retention, outages, persistence and resource measurements
have actually passed. No application migration or hosted readiness is involved.
