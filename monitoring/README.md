# Local monitoring foundation — issue #58

Current M9 is observability; historical `docs/milestone9/` deployment work belongs
to M15. This optional stack implements T1 of the
[task plan](../docs/milestone9-observability/milestone-9-observability-task.md).
See the [verification](../docs/milestone9-observability/verification-milestone9-issue58.md),
[resource experiment](../docs/milestone9-observability/performance-milestone9-issue58.md)
and [implementation checkpoints](../docs/milestone9-observability/implementation-issue58.md)
for dated evidence and retained failures. The [original experiment declaration](../docs/milestone9-observability/experiment-milestone9-issue58.md)
is preserved separately from these current operating instructions.

## Understand the flow

```text
Synthetic producer -- OTLP/HTTP JSON --> Collector Contrib
                                          |-- metrics endpoint <-- Prometheus scrape
                                          |-- OTLP/HTTP logs ----> Loki
                                          `-- OTLP/HTTP traces --> Tempo
Grafana ------------------------------------> Prometheus / Loki / Tempo
```

Metrics describe counts/distributions, logs preserve individual observations and
traces connect operations. Collector receives and routes signals; the three
stores persist them. Grafana queries those stores through authenticated proxy
APIs. The temporary synthetic producer is acceptance infrastructure, outside the
five permanent services. Application instrumentation, restricted PostgreSQL/Redis
collection, operational dashboards and alert objectives belong to #59–#67.

## Operate the stack

Follow [the runbook](../docs/runbooks/monitoring.md) for setup, shutdown and diagnosis.
From the repository root with Python 3.12 and Docker Desktop/Compose:

```sh
backend/.venv/bin/python scripts/local-monitoring.py init
backend/.venv/bin/python scripts/local-monitoring.py config
backend/.venv/bin/python scripts/local-monitoring.py up
backend/.venv/bin/python scripts/local-monitoring.py status
backend/.venv/bin/python scripts/generate-monitoring-telemetry.py --endpoint http://localhost:4318 --duration 10
backend/.venv/bin/python scripts/local-monitoring.py down
```

Grafana defaults to `http://localhost:3001`, leaving frontend port 3000 available.
Choose alternate ports on `init` using `--grafana-port` and `--otlp-port`.
Initialization refuses existing state and creates independent credentials in the
ignored, private `.local-monitoring/` directory. Read the credential files locally
when signing in; never copy them into diagnostics. Normal shutdown retains data.
Keep the ownership manifest; the helper provides no developer-volume deletion.

`compose.yaml` has a project-scoped internal bridge and no published ports.
`compose.host.yaml` additionally publishes Grafana/Collector on loopback and adds
an ingress bridge for those two services. Stores remain internal. Container
acceptance publishes only an ephemeral loopback Grafana port, sends OTLP over
the internal network and owns its separate random test project. Local Compose
file secrets are read-only mounts, not an encrypted vault.

## Bounds and persistence

| Service | Hard memory bytes | Persistent path |
|---|---:|---|
| Collector | 250,000,000 | None; bounded disposable queues |
| Prometheus | 300,000,000 | `/prometheus` |
| Grafana | 650,000,000 | `/var/lib/grafana` |
| Loki | 400,000,000 | `/loki` |
| Tempo | 400,000,000 | `/var/tempo` |
| Total | 2,000,000,000 | Four project-owned named volumes |

Memory plus swap equals each memory limit. Collector's Go target is 200 MB,
its memory limiter is 160 MiB with a 32 MiB spike allowance; Grafana's Go target
is 420 MB. These soft controls do not replace engine limits. Grafana's original
350 MB allocation failed startup; the revised split above preserved the total.
The failed attempts remain in the evidence directory.

Containers use nonroot users, read-only roots, dropped capabilities, no new
privileges, bounded PIDs and 16 MiB temporary filesystems. Configuration mounts
are read-only and refuse missing host files. JSON container logs rotate at two
5 MiB files each. Restart attempts are bounded; readiness is polled explicitly.
No application network, database, Redis, cloud service or startup migration is
involved. Temporary producer/reader containers have separate 128 MB limits.

Prometheus retains seven days; Loki and Tempo retain 72 hours. Loki has persistent
WAL/index/chunks/compactor state with deletion enabled; Tempo has persistent local
WAL/blocks with compactor cleanup. Normal shutdown retains these volumes.
Time retention is asynchronous and is not a byte quota. Active data, WAL,
compaction and deletion delay require disk headroom. Read the measured initial
disk budget before unattended use; image/build caches are separate.

## Collector and data contracts

`otel-collector.yaml` enables OTLP/HTTP only, bounds request bodies at 64 KiB and
runs memory limiting, synthetic filtering/sanitization and batching. Logs and
traces each have a 4 MiB serialized-byte queue, two consumers, nonblocking
overflow, two-second export timeout and bounded retry sequences (one–two-second
intervals, ten-second maximum elapsed retry). That retry bound is not a queue
residence TTL. In-memory queues can lose data on forced shutdown/process failure.
No raw debug exporter or stdout collection duplicates the log pipeline.

Only service `restaurantos-monitoring-synthetic`, spans `synthetic.operation` and
`synthetic.child`, and these three metrics are admitted:

| OTLP metric | Prometheus series | Meaning |
|---|---|---|
| `restaurantos.synthetic.operations` | `restaurantos_synthetic_operations_total` | Cumulative operation count |
| `restaurantos.synthetic.duration` | `restaurantos_synthetic_duration_seconds_*` | Manufactured seconds histogram |
| `restaurantos.synthetic.last_observation` | `restaurantos_synthetic_last_observation_seconds` | Last observation Unix timestamp |

Arbitrary attributes/scope data, events, links, exemplars, tracestate and status
text are removed; the log body and severity are fixed. Trace/log IDs remain
metadata, not metric or Loki index labels. These checks protect the synthetic
fixture; application/framework privacy remains #59's responsibility. The
Collector exports a distinct internal self-metrics endpoint for Prometheus.
Self-health does not prove destination health, delivery or freshness. An expired
series, old timestamp or missing scrape is not healthy zero activity.

The generator uses standard-library OTLP/HTTP JSON with deterministic IDs from
seed/sequence. Payload splitting uses actual encoded bytes. It reports phase
counts, acknowledgements and pacing misses, and never automatically replays an
uncertain export. A successful send is checked separately against stored data.
Normal proposal for this small local synthetic workload is 100% trace emission;
application sampling must be measured and reconsidered with #59/#65.

## Compatibility and immutable images

`images.lock.json` records exact multi-platform image digests, source commits and
reviewed immutable documentation. Both ARM64/AMD64 manifests were inspected;
actual binaries and runtime acceptance were checked on native ARM64 only.
Ordinary validation uses the committed references and does not resolve updates.
A deliberate pin change must review matching upstream documentation, verify the
index digest/platforms and repeat parser, signal, retention and resource checks.

Collector Contrib 0.164.0 includes the required receiver, processors and exporters.
Native inventory/parser execution verified the locked component configuration.
OTLP HTTP JSON feeds the Prometheus exporter and `otlp_http` exporters to Loki's
native `/otlp` endpoint and Tempo's HTTP receiver. Loki structured metadata is
enabled. Grafana automatic plugin preinstallation/startup updates are disabled, so it
does not fetch unpinned startup plugins. Grafana provisions stable read-only
source UIDs and trace/log links;
`$${__value.raw}` escapes its provisioning environment expansion.

The bundled beta PostgreSQL/Redis receivers were inspected against versioned
source. They remain disabled. #61 must establish exact restricted grants/ACLs,
query cost, cadence and actual PostgreSQL 16/Redis 7 compatibility; component
presence alone grants no database access and proves no runtime compatibility.

## Reproduce the evidence

Use [the testing guide](../docs/testing/monitoring.md) for both connection modes,
restart, 180-second destination outages, scraper gaps, reduced-queue saturation,
intentional failure cleanup, physical retention and full resource trials.
`check-monitoring-config.py` runs the four locked parsers in bounded,
network-disabled containers. The shared baseline renders both Compose models;
backend-unit protects the pure contracts and backend-static checks the helpers.

Acceptance uses random `restaurantos-monitoring-test-*` projects and private
credentials. Cleanup selects exact project labels and rejects developer-volume
deletion. No developer state or application data is used. Retained reports include
failures as well as successful checks. Synthetic local acceptance does not
establish M9's end-to-end application/worker trace or incident exit criteria,
all-ten-gate acceptance, hosted capacity or AMD64 runtime behavior.
