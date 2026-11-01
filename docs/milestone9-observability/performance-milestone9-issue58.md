# Issue #58 local monitoring resource prototype

Protocol declared before measurement, 2026-11-01 (Asia/Bangkok).
Status: four corrected-profile trials passed locally; one additional timing attempt failed and is retained. This is synthetic transport/storage evidence, not
application capacity, a service objective or full M9 acceptance.

## Fixed experiment

One host run and three fresh container-mode repetitions run sequentially. Each
uses five operations/second, 120 seconds warmup and 600 seconds measurement in
one producer process: 3,600 logs/traces, 7,200 spans, a final cumulative count of
3,600 and a manufactured duration histogram sum of 63 seconds. The measured phase
has 3,000 operations and a 52.5-second histogram sum. All traces are emitted.
No other monitoring stack may be running. Failed runs are retained, not averaged
away or overwritten. The observer smoke passed before measurement.

The fixed hard limits total 2,000,000,000 bytes: Collector 250 MB, Prometheus
300 MB, Grafana 650 MB, Loki 400 MB and Tempo 400 MB. Image references are those
in `monitoring/images.lock.json`. Each report fingerprints its configurations,
producer/observer source and image identities, engine architecture/CPU/memory,
background-container count and exact producer settings.

```sh
backend/.venv/bin/python scripts/benchmark-monitoring.py --mode host --report docs/milestone9-observability/evidence/issue58/step9-fixed-host-r1.json
backend/.venv/bin/python scripts/benchmark-monitoring.py --mode container --report docs/milestone9-observability/evidence/issue58/step9-fixed-container-r1.json
backend/.venv/bin/python scripts/benchmark-monitoring.py --mode container --report docs/milestone9-observability/evidence/issue58/step9-fixed-container-r2-retry1.json
backend/.venv/bin/python scripts/benchmark-monitoring.py --mode container --report docs/milestone9-observability/evidence/issue58/step9-fixed-container-r3.json
```

## Pre-measurement correction, 09:56 UTC

The original host and first container trials passed functional/resource checks,
but their Grafana startup volumes differed. Inspection found default downloaded
plugins (`grafana-advisor-app`, `grafana-pyroscope-app`, `mssql`). The pinned image
had automatic preinstallation enabled. Those two reports are retained as
candidate observations, not final fixed-profile acceptance. The second container
candidate was deliberately interrupted; its failed report verifies cleanup. A
fourth candidate was never started. `step9-profile-correction.json` records this.

Before the four final trials, automatic plugin preinstallation and startup updates
were disabled explicitly. The actual running plugin directory was empty. The
benchmark now requires that condition and fingerprints the checker, lifecycle
helper and image lock as well as its previous inputs. Workload, timing, five
images and the 2 GB total are unchanged. The retained 650 MB Grafana limit is
not claimed to be the minimum needed with plugins disabled; no new allocation
optimization was mixed into the corrected experiment. All final results use the `step9-fixed-`
prefix; no candidate/final measurements are pooled.

## Retained corrected-profile timing failure

`step9-fixed-container-r2.json` generated all 3,600 operations and acknowledged
all 1,809 requests, with no failed/uncertain request, but recorded one pacing
miss over the declared 50 ms threshold. It correctly failed before downstream
reconciliation/final disk inspection; owned cleanup passed. Its cause is not
established. This failure remains visible and is not included in passing-cell
resource aggregates. The identical fresh retry is `step9-fixed-container-r2-retry1`;
timing tolerance, workload and configuration were not relaxed. A successful
retry cannot establish consistently uninterrupted pacing or application capacity.

## Measurement interpretation

Streaming Docker stats begin after readiness. Memory is Docker's cache-adjusted
working set, converted from its rounded display; raw strings are retained. CPU
percent treats one logical CPU as 100 percent. Terminal rendering controls are
removed from the JSON stream; blank control frames are not samples. Unique
short/full container IDs are resolved explicitly; ambiguous or malformed samples
fail rather than becoming healthy zero. The observer was checked against native
streaming output before the long experiment.

Per-service peaks and means use the declared ten-minute wall-clock window.
Aggregate peaks sum the last observations within complete one-second buckets;
they are sampled near-concurrent values, not continuous maxima or a sum of each
service's independent peak. "Complete" means all five services are present;
clock-second boundary buckets can be partial, so a 600-second window can contain
601 such buckets. Report sample counts and maximum intervals. Startup
CPU/memory peaks before readiness and host-observer RSS are not measured.

Read-only volume inspections record both logical and allocated bytes before
startup, after startup, at the producer's warmup boundary and after measurement.
The boundary snapshot completes after the event; its actual timestamp is retained.
The final snapshot follows the ten-second producer hold and reader execution.
Growth rates divide by actual snapshot timestamps rather than assuming exactly
600 seconds. WAL allocation, caches and compaction make growth nonlinear. Temporary readers
have 128 MB caps; container producers have a separate 128 MB cap. These are
additional test resources, not part of the five-container sum. Observer overhead
is disclosed, not claimed to be precisely accounted for.

Pass requires complete producer pacing/acknowledgements, exact backend counts
through Grafana, no observed export/refusal failures, no OOM/restarts and verified
owned cleanup. Data absence after generation must not be relabeled zero. Numeric
metrics are synthetic; no financial calculations or business totals are involved.

## Results and initial disk budget

Four corrected-profile trials passed (one host, three container), alongside the
retained failed timing attempt described above. The four passing trials had identical recorded inputs,
producer filesystem layers/runtime configuration and engine capacity. Each reconciled 3,600 operations,
3,600 logs and 3,600 distinct trace IDs; the expected two-span fixture totals
7,200 spans, with parentage/log linkage spot-checked. Counter/histogram counts
were exact and the histogram sum was 63 seconds. Each producer reported zero
pacing misses and failed/uncertain requests. No OOM/restarts or nonzero observed
export/refusal counters occurred. All four owned cleanups passed.

The engine was native `aarch64`, Docker 29.9.2, eight logical CPUs and
8,319,770,624 allocated memory bytes. The host observer used Python 3.12.16;
Compose was v5.6.1. The producer uses the pinned Python 3.12 image, with its
content identity recorded in each report.
The design's user-reported 7.49 GB is a historical planning input, not this
engine observation. No background container was running before any trial.
Host CPU was shared with ordinary host activity; it was not isolated.

The CLI yielded roughly two samples/second/service, rather than the originally
planned one: 1,200 observations/service in each 600-second measurement window.
Actual maximum gaps are below. This cadence was identical across the fixed
trials; no continuous peak or exact process-RSS claim is made.

| Trial | Aggregate sampled peak MB | Aggregate sampled peak CPU % | All-five buckets | Reconciliation/inspection settlement after last operation (s) |
|---|---:|---:|---:|---:|
| host-r1 | 928.4 | 25.37 | 600 | 16.639 |
| container-r1 | 880.1 | 24.84 | 601 | 16.468 |
| container-r2-retry1 | 895.3 | 24.48 | 601 | 16.471 |
| container-r3 | 909.0 | 24.07 | 601 | 16.473 |

MB is decimal; CPU 100% is one logical CPU. All settlements were within the
declared 120-second allowance. A settlement includes the final producer hold,
disk inspection and query checks, not just network export latency.

| Trial | Service | Peak sampled MB | Mean CPU % | Peak sampled CPU % | Samples | Maximum sample gap (s) |
|---|---|---:|---:|---:|---:|---:|
| host-r1 | collector | 70.9 | 0.675 | 3.83 | 1200 | 0.512 |
| host-r1 | prometheus | 76.3 | 0.970 | 4.02 | 1200 | 0.512 |
| host-r1 | grafana | 374.2 | 1.607 | 16.19 | 1200 | 0.512 |
| host-r1 | loki | 106.5 | 1.699 | 5.32 | 1200 | 0.512 |
| host-r1 | tempo | 305.3 | 1.055 | 20.96 | 1200 | 0.512 |
| container-r1 | collector | 64.3 | 0.645 | 3.28 | 1200 | 0.506 |
| container-r1 | prometheus | 76.3 | 0.912 | 3.90 | 1200 | 0.506 |
| container-r1 | grafana | 363.8 | 1.598 | 9.83 | 1200 | 0.506 |
| container-r1 | loki | 108.4 | 1.702 | 11.36 | 1200 | 0.506 |
| container-r1 | tempo | 276.9 | 1.078 | 21.53 | 1200 | 0.506 |
| container-r2-retry1 | collector | 65.9 | 0.618 | 4.95 | 1200 | 0.506 |
| container-r2-retry1 | prometheus | 72.1 | 0.945 | 3.39 | 1200 | 0.506 |
| container-r2-retry1 | grafana | 378.6 | 1.580 | 15.31 | 1200 | 0.506 |
| container-r2-retry1 | loki | 108.6 | 1.670 | 5.74 | 1200 | 0.506 |
| container-r2-retry1 | tempo | 287.1 | 1.070 | 20.23 | 1200 | 0.506 |
| container-r3 | collector | 69.8 | 0.624 | 3.32 | 1200 | 0.505 |
| container-r3 | prometheus | 74.5 | 0.957 | 3.68 | 1200 | 0.505 |
| container-r3 | grafana | 367.5 | 1.624 | 15.41 | 1200 | 0.505 |
| container-r3 | loki | 98.2 | 1.771 | 6.63 | 1200 | 0.504 |
| container-r3 | tempo | 315.2 | 1.037 | 17.73 | 1200 | 0.504 |

### Volume observations

All four volumes were empty before startup. These are file bytes inside the
volumes, including active WAL/index/block data; Docker image/build cache and
container writable layers are separate. Empty plugin directories were required.

| Trial | Volume | Allocated after startup (bytes) | Allocated after warmup | Allocated after measurement/hold | Logical after measurement/hold |
|---|---|---:|---:|---:|---:|
| host-r1 | prometheus | 147456 | 577536 | 2871296 | 2867747 |
| host-r1 | grafana | 1667072 | 1667072 | 1667072 | 1662976 |
| host-r1 | loki | 45056 | 204800 | 1040384 | 1032418 |
| host-r1 | tempo | 0 | 868352 | 2576384 | 2454385 |
| container-r1 | prometheus | 139264 | 581632 | 2875392 | 2873213 |
| container-r1 | grafana | 1667072 | 1667072 | 1667072 | 1662976 |
| container-r1 | loki | 45056 | 204800 | 1044480 | 1035475 |
| container-r1 | tempo | 0 | 864256 | 2609152 | 2482874 |
| container-r2-retry1 | prometheus | 147456 | 577536 | 2879488 | 2871210 |
| container-r2-retry1 | grafana | 1662976 | 1662976 | 1662976 | 1658880 |
| container-r2-retry1 | loki | 45056 | 204800 | 1040384 | 1028733 |
| container-r2-retry1 | tempo | 0 | 864256 | 2580480 | 2458034 |
| container-r3 | prometheus | 143360 | 581632 | 2879488 | 2873399 |
| container-r3 | grafana | 1667072 | 1667072 | 1667072 | 1662976 |
| container-r3 | loki | 45056 | 204800 | 1048576 | 1038110 |
| container-r3 | tempo | 0 | 864256 | 2600960 | 2480030 |

Owned post-run volumes were removed, verified by exact project labels. This is
cleanup evidence, not a measurement of application disk use. Accelerated
compaction/deletion is independently demonstrated by the retained Step 8 fixture;
these short resource runs do not reach natural multi-day steady-state retention.

### Initial retention disk allowance

For each store, take the maximum positive allocated growth rate between warmup
and the final snapshot across the four trials. Multiply by its retention
seconds (seven days for Prometheus, three for Loki/Tempo; Grafana is an initial
state allowance), add the maximum final allocation, double that subtotal, add
512 MiB for active/WAL/compaction slack and round up to GiB. Add a 64 MiB
container-log allowance and 25% overall reserve, rounded up again. The factors
are engineering planning headroom, not a measured confidence interval or quota.

| Volume | Worst observed allocated growth (bytes/s) | Maximum final allocated bytes | Linear retained growth (bytes) | Initial allowance GiB |
|---|---:|---:|---:|---:|
| prometheus | 3773.279 | 2879488 | 2282078968 | 5 |
| grafana | 0.000 | 1667072 | 0 | 1 |
| loki | 1383.033 | 1048576 | 358482107 | 2 |
| tempo | 2859.940 | 2609152 | 741296448 | 2 |

The resulting initial telemetry allowance is **13 GiB**, plus separate Docker
image/build cache. This is a proposed local planning reserve, not an enforced
per-volume byte ceiling. Check available Docker/host storage before unattended
use. Bursts, new labels, user activity, compaction and multi-day WAL behavior can
exceed this short-run extrapolation; nominal retention can fail under pressure.
No deployment or full-retention capacity guarantee is inferred.

Locally rebuilt producer IDs differed across trials. Image inspection verified
identical filesystem layers and runtime configuration; metadata, descriptor and
identity fields differed. `step9-generator-provenance.json` records each ID,
layers and configuration hash. This does not claim reproducible build metadata.

Raw reports and `step9-summary.json` retain all inputs, source/report hashes,
samples and calculations. The summary verifies the four hashes agree and match
the measured working tree. The uncontrolled candidates and intentional
interruption remain separate in `step9-profile-correction.json`.
