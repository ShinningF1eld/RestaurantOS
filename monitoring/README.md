# Local monitoring foundation — issue #58

Status: Steps 1–6 configured and checked; full T1 acceptance remains pending.
Recorded 2026-11-01 (Asia/Bangkok) against RestaurantOS
`50160a1a00d7261971e8fb7d72fdb8238224e7fe`.

This directory starts [issue #58](https://github.com/ShinningF1eld/RestaurantOS/issues/58),
T1 of the [current M9 observability task plan](../docs/milestone9-observability/milestone-9-observability-task.md).
It implements the foundation described by requirements R1, R2, R6 and R9 of the
[observability design](../docs/milestone9-observability/milestone-9-observability-design.md).
Historical `docs/milestone9/` deployment work belongs to current M15.

## What this step establishes

The experiment and image identities are fixed before collecting results. Steps 2
and 3 add Compose wiring and service configurations. A small four-service smoke
has passed; Grafana provisioning, the permanent synthetic generator, lifecycle
helpers and acceptance verification follow in the sections below. Full-stack
startup is available through the Step 6 lifecycle helper. No application code,
dependencies, schema, database, cloud
resources or required gate names are changed by these steps.

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

## Compose wiring — Step 2

[compose.yaml](compose.yaml) describes the five services on a project-owned
internal bridge. It publishes no host ports and connects to no application
network or database. Each image reference is copied exactly from the lock;
pure regressions check for drift. A temporary acceptance generator will join the
same project network. `--project-name` scopes resources so later acceptance runs
can use unique projects without sharing developer volumes.

[compose.host.yaml](compose.host.yaml) is an explicit additional file that
publishes only Grafana on `127.0.0.1:3001` and Collector OTLP/HTTP on
`127.0.0.1:4318`. Override `MONITORING_GRAFANA_PORT` or
`MONITORING_OTLP_HTTP_PORT` when occupied; `0` requests an ephemeral host port for
later acceptance runs. Container target ports remain fixed. No storage API, OTLP
gRPC listener, health endpoint or metrics endpoint is published. Step 3's first
runtime probe found that the internal-only bridge made the host port unusable on
this Docker setup. The overlay now adds a second ordinary bridge, `host_ingress`,
for Grafana/Collector only. Storage remains internal. A corrected host OTLP smoke
passed; Grafana itself remains unverified until Step 4.

The initial split uses decimal bytes, with equal `mem_limit` and `memswap_limit`
so Docker does not grant an additional swap allowance:

| Service | Hard memory bytes | Decimal MB | Writable persistent volume |
|---|---:|---:|---|
| Collector | 250,000,000 | 250 | None; bounded best-effort queues in memory |
| Prometheus | 300,000,000 | 300 | `prometheus_data` at `/prometheus` |
| Grafana | 650,000,000 | 650 | `grafana_data` at `/var/lib/grafana` |
| Loki | 400,000,000 | 400 | `loki_data` at `/loki` |
| Tempo | 400,000,000 | 400 | `tempo_data` at `/var/tempo` |
| Total | 2,000,000,000 | 2,000 | Project-scoped volumes; no fixed/external names |

Loki and Tempo get the larger initial shares for ingestion, querying and
compaction. This is an unmeasured starting allocation, not a capacity result.
Collector's `GOMEMLIMIT=200000000B` is a soft Go runtime target below its hard
limit; it neither caps all process memory nor replaces Step 3's memory limiter.
Normal shutdown will retain these volumes. Deletion of acceptance volumes belongs
to the ownership-checked helper in Step 6, not a generic cleanup command here.

Services use read-only root filesystems, drop Linux capabilities, prohibit gaining
privileges and have a 256-process limit. Their `/tmp` tmpfs is bounded to 16 MiB
and counts toward container memory; the named data volumes remain writable.
Container JSON logs rotate at two 5 MiB files per service. Restart attempts are
bounded to three on failure, and stop grace is 30 seconds. No startup ordering is
presented as readiness; later verification will poll real readiness endpoints.

Configuration binds are read-only with `create_host_path: false`. Missing files
must fail startup instead of silently creating directories. Step 3 supplies
`otel-collector.yaml`, `prometheus.yaml`, `loki.yaml` and `tempo.yaml`.
`grafana/provisioning/` remains Step 4 work. Loki durable/Compactor paths are
under `/loki` and Tempo WAL/block paths under `/var/tempo`. Prometheus's command
already selects `/prometheus` and seven-day retention; size budgeting remains
measurement work.

Grafana anonymous access and signup are disabled now, before host exposure is
added. Admin username/password are read from Compose secret files in the required
`MONITORING_STATE_DIR`, with no tracked credential defaults. Step 4/6 will supply
private-file initialization. The normal repository-local state location
`.local-monitoring/` is already ignored; that small ignore rule was brought forward
from Step 4 so runtime secrets cannot accidentally be tracked. File-based local
Compose secrets are mounted files, not an encrypted secret-management service.

From the repository root, validate the models without creating secret files,
pulling images or contacting the Docker engine:

```sh
MONITORING_STATE_DIR="$PWD/.local-monitoring" docker compose -f monitoring/compose.yaml config --quiet
MONITORING_STATE_DIR="$PWD/.local-monitoring" docker compose -f monitoring/compose.yaml -f monitoring/compose.host.yaml config --quiet
```

These commands check Compose syntax/interpolation only; they do not check that
the future configuration/secret files exist or validate service-specific settings.
Leaving `MONITORING_STATE_DIR` unset fails interpolation deliberately. Supplying
an absolute directory is the caller's responsibility until the lifecycle helper
can enforce it. Do not run the full-stack `up` until Grafana provisioning and
secret initialization are available. Applied engine limits, nonroot data paths,
readiness and small-fixture delivery passed for the four non-Grafana services;
restart persistence, retention deletion and full resource acceptance remain open.

Pure regressions in `backend/tests/unit/test_monitoring_compose.py` protect the
image lock, combined budget, internal/project-owned resources, host exposure and
secret/configuration mount rules. They run in the existing backend-unit gate
without Docker or services. The secret baseline contains reviewed entries for
the lock's exact public commit IDs and documentation hashes; detector settings
and existing findings are unchanged.

## Signal configuration — Step 3

[otel-collector.yaml](otel-collector.yaml) enables only OTLP/HTTP ingestion, with
a 64 KiB request-body cap, no client metadata forwarding and bounded HTTP waits.
Each pipeline runs memory limiting first, then filtering/sanitization, then
one-second batching (at most 128 records/data points per batch). The memory
limiter's 160 MiB hard threshold and 32 MiB spike allowance sit below the
250 MB container limit. These are process protection settings, not a measured
capacity guarantee.

The foundation policy accepts only `restaurantos-monitoring-synthetic`, the span
names `synthetic.operation`/`synthetic.child`, and the three metric names below.
It drops arbitrary resource/scope/record attributes, span events and linked spans;
replaces log bodies with `synthetic operation completed`; clears span status text
and tracestate; and fixes scope/metric label values. Metric exemplars are excluded
from this initial fixture. This intentionally narrow policy is not an application
logging policy or an authentication boundary. #59 must review application fields,
framework/exception paths and remaining OTLP metadata before broadening it.

| Input metric | Prometheus output | Meaning |
|---|---|---|
| `restaurantos.synthetic.operations`, unit `1` | `restaurantos_synthetic_operations_total` | Cumulative synthetic operation count. |
| `restaurantos.synthetic.duration`, unit `s` | `restaurantos_synthetic_duration_seconds_{bucket,count,sum}` | Explicit histogram of manufactured durations in seconds. |
| `restaurantos.synthetic.last_observation`, unit `s` | `restaurantos_synthetic_last_observation_seconds` | Unix time of the last generated observation; not a duration or progress guarantee. |

The last-observation gauge supplements Step 1's counter/histogram to distinguish
stopped generation from a still-healthy scrape target. The exporter expires
unupdated workload series after 30 seconds; absence stays absent rather than
being coerced to zero. It does not forward producer timestamps as scrape sample
timestamps. No tenant/user/order/event/trace IDs become metric labels.

Logs and traces each use a separate 4 MiB serialized-byte export queue, two
consumers, two-second attempt timeouts and retries capped at ten seconds per
retry sequence. Queue insertion neither waits for export nor blocks on overflow.
This is not a ten-second queue residence deadline, and encoded queue size is not
the total heap size. Large backlogs can outlive the 30-second Docker stop grace;
forced termination may lose queued telemetry. There is no persistent queue or
promise to recover lost signals. Saturation/shutdown pressure remain later tests.

[prometheus.yaml](prometheus.yaml) scrapes every five seconds with a two-second
timeout. Workload export at `collector:8889` is separate from Collector self-metrics
at `collector:8888`. Additional jobs scrape Prometheus, Loki and Tempo. Per-job
sample limits bound ingestion; workload labels also have length/count limits.
No application targets, remote-write destination, DB/Redis receiver or alert rule
is enabled. Use scrape `up`, fresh observation time and queue/export counters
together; process health does not establish fresh or complete workload delivery.

[loki.yaml](loki.yaml) configures single-process filesystem/TSDB v13 storage with
24-hour indexes, persistent WAL/index/chunk/Compactor paths, structured metadata,
and only `service.name` as an OTLP index label. Its Compactor applies 72-hour
retention on a five-minute cycle with a ten-minute deletion delay and two deletion
workers. Query concurrency and ingestion are limited; pattern ingestion and usage
reporting are disabled. Its unauthenticated API must remain on the internal network.

[tempo.yaml](tempo.yaml) enables only OTLP/HTTP trace reception and local WAL/block
storage. It configures 72-hour retention, five-minute compaction cycles, ten-minute
compacted-block retention, limited query/ingestion concurrency and trace sizes,
and no external cache, Kafka or metrics-generator dependency. Usage reporting is
disabled. Both stores perform asynchronous cleanup: three-day retention does not
mean physical deletion occurs exactly at the 72-hour boundary or bound disk bytes.

Collector health is internal port 13133. Its diagnostics remain JSON stderr with
no debug exporter or second stdout ingestion path; they are not duplicated into
Loki. Inspect available self-metrics for receiver refusals, export failures,
enqueue failures and queue size/capacity. Exact field names follow the pinned
binary; downstream outages cannot be inferred from a health response alone.

Validate service-specific syntax using the actual locked binaries:

```sh
backend/.venv/bin/python scripts/check-monitoring-config.py
```

This creates network-disabled parser containers and removes each by its unique
name. It may fetch the exact locked image if not cached. All four parsers passed
on native ARM64. The [dated Step 3 evidence](../docs/milestone9-observability/verification-milestone9-issue58-step3.md)
records both the failed network probe and corrected synthetic smoke, tested
canary paths and the limitations of that one-operation experiment.

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
both source revisions. Step 3's actual binary inventory confirms the required
components, including the still-disabled PostgreSQL/Redis receivers; the lock
links that evidence without changing any image reference.

Registry inspection used anonymous Docker Registry v2 manifest reads. The
SHA-256 of each index response matched its `Docker-Content-Digest` header, and its
manifest list advertised both required platforms. During Step 1 no image layers
were pulled or containers run. Source tags were resolved to commit IDs; the lock
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

## Grafana provisioning — Step 4

`grafana/provisioning/datasources/datasources.yaml` declares stable Prometheus,
Loki and Tempo UIDs, internal proxy URLs and trace/log links. Provisioned sources
are read-only in the UI. Grafana performs its own dollar-variable expansion, so
the trace-link expression is escaped as `$${__value.raw}` in this YAML.

The initial 350 MB Grafana allocation failed startup (exit 137; the second run
confirmed OOM). A Go heap target alone did not fix it. Before retrying, the same
2,000,000,000-byte total was reallocated to the table above: Grafana 650 MB,
Collector 250 MB, Prometheus 300 MB, Loki/Tempo 400 MB each. Collector's limiter
was reduced to 160 MiB and its Go target to 200 MB; Grafana uses a 420 MB Go target.
Both failed attempts are retained under the issue58 evidence directory. These
changes do not raise the total budget or establish sustained capacity.

Private Grafana bootstrap files must be readable by container UID 472. Lifecycle
initialization (Step 6) will keep their containing host directory private and
mount the files read-only; Compose's local file secrets do not implement requested
UID remapping. No password belongs in tracked YAML or retained reports.

## Synthetic generator — Step 5

Build the temporary producer from the repository root:

```sh
docker build -f monitoring/synthetic/Dockerfile -t restaurantos-monitoring-generator:local .
```

For a running host-mode stack, use the generator script with the loopback OTLP
origin. For the declared workload, pass `--rate 5 --duration 720 --warmup 120`.
The same arguments work in the image with `--endpoint http://collector:4318`
when its temporary container joins the owned project's monitoring network.
The later acceptance runner handles those names/ports and cleanup. `--canary`
adds only synthetic private markers for filtering checks. Trace IDs derive from
`--seed` and sequence; they never become metric labels. No SDK or application
dependency was added. Exit 1 means incomplete pacing or failed/uncertain export;
the summary is not proof of downstream delivery, which must be queried separately.

## Local lifecycle — Step 6

From the repository root, with the locked backend test environment and local Docker:

```sh
backend/.venv/bin/python scripts/local-monitoring.py init
backend/.venv/bin/python scripts/local-monitoring.py config
backend/.venv/bin/python scripts/local-monitoring.py up
backend/.venv/bin/python scripts/local-monitoring.py status
backend/.venv/bin/python scripts/local-monitoring.py down
```

Choose different ports on `init` with `--grafana-port` / `--otlp-port` if needed.
The ignored `.local-monitoring/` directory holds the username/password files and
ownership manifest; credentials are not printed. Initialization never replaces
existing state. Read the private credential files locally when signing into
Grafana; do not paste them into retained diagnostics. `down` retains telemetry and
Grafana's database. There is intentionally no developer volume-delete command.
Acceptance uses separate `restaurantos-monitoring-test-*` projects and temporary
state; it cannot use the development deletion path. Do not remove the state
directory while its containers/volumes are still needed to identify that project.
