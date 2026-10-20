# Milestone 8 worker database-pool comparison

Measured 2026-10-20 (Asia/Bangkok), continuing locally after the user cancelled
the cloud transfer. Base: `codex/m8-relay-drain` at
`f1d61c1648ea5450d509120eb76ba3cf4b2826ef`. The original, busy-reference and relay
reports remain historical evidence. Both pushed checkpoints were checked on
2026-10-20: all ten jobs and `Milestone 6 acceptance` passed for
[relay f1d61c1](https://github.com/ShinningF1eld/RestaurantOS/actions/runs/39285105654)
and [busy b9b6931](https://github.com/ShinningF1eld/RestaurantOS/actions/runs/39284501272).
Those runs do not validate this subsequent pool change. The user later authorized
publication/merge; its associated PR records the required new-source CI results.

## Finding and bounded change

The old paced sink spent most of its delay waiting to start execution. In relay
paced-1 logs, publication-observation to attempt-start P95 was approximately
36.96s; attempt-start to completion-log P95 was 0.366s. These wall-clock log
stages are diagnostic approximations, not commit timestamps or the authoritative
benchmark timing bounds. They do not separately measure lock, SQL or connect time.

A fresh unchanged relay control reproduced sink P95 28.226s. Disabling only the
fast busy-reference queue gave 28.780s, with correct effects in both runs. Neither
fresh control routed a busy outcome; removing this scheduling feature cannot
explain or fix their sink backlog. These are sequential single controls, not a
randomized significance test. No autoscaling or additional worker was introduced.

Inspection identified a major environmental difference: `app/db/database.py`
uses `NullPool` in test mode for HTTP tests running on independent event loops.
The standalone worker imported that session factory, establishing a new asyncpg
connection for every transaction in these benchmarks. Normal-mode workers
already used SQLAlchemy's default pool. The worker now creates its own bounded
pool for each invocation/event loop, using the supplied settings, and disposes
it on exit. The maximum is `4 + relay_concurrency` (six by default), no overflow,
five-second checkout timeout and pre-ping on reuse. The API pool is unchanged.

**This removes a test-mode connection penalty and verifies a consistent worker
resource lifecycle. It does not demonstrate an equivalent production speedup.**
The same settings/workload comparison below supports the connection-lifecycle
change as the cause of the observed local improvement, without quantifying each
connect/SQL/lock cost. A representative normal-mode target-host comparison is
still needed before any production capacity claim.

Only production `app/worker.py` and new `app/db/worker.py` change. The process-test
helper uses the same pool factory so crash-boundary tests exercise it. Business
producers, handlers, two consumer transactions, durable receipts, persisted due
times, eight charged attempts, claim fencing, relay scheduling, busy revisits,
Redis budgets, API/UI/schema and dependencies retain their current behavior.

## Reproduction and source identity

Use all five unchanged commands in the
[benchmark procedure](../testing/event-freshness-benchmark.md), changing only
output names to `test-results/worker-db-pool-<cell>.json`. Three paced repetitions:
40 bundles at 0.5/s, first with `--operations`; pressure: 40 at 2/s with the
240-second watchdog; light: 20 at 0.25/s. Producer concurrency four, polling 25ms,
one worker with three serial consumer loops and unchanged default worker settings.
All five cells ran serially after unit/static checks, without concurrent tests,
builds or other benchmarks, against fresh guarded disposable databases and Redis.
Only local report reads/writes occurred during measurement.

Each bundle is the same eight committed events and eleven required effects:
two analytics, two alerts, seven sink, including the actual authorized low-stock
inventory service write. Six order/menu events are projection fixtures, not full
HTTP lifecycle throughput. Forty bundles yield 320 events/440 effects, 500.00
sales, 40 orders/episodes/stubs and 240 diagnostics; light halves these counts.
No warm-up samples are discarded. No application database is read or migrated.

Host/tooling matches the earlier Windows measurements: Python 3.12.13,
PostgreSQL 16.15, Redis 7.4.11, Windows 11, i5-12400F/12 logical CPUs/15.82 GiB host
RAM and Docker 12 CPUs/about 8 GiB. Exact versions/settings/environment remain
in each raw report. Script version 1.0.0 is unchanged. Migration head in these
disposable databases is `c3d8e1f52a74`; it is not an application revision claim.

The seven raw JSON files in [worker-db-pool/](benchmarks/worker-db-pool/) are copied
byte-for-byte from the runner. Their repository-head field is f1d61c1 because
the pool implementation was measured uncommitted above that checkpoint.
Production source fingerprints at measurement (SHA256):

| File | SHA256 |
|---|---|
| `backend/app/worker.py` | `011860549935bf3056f6f5ed50529a13d4c06271c2b46942c21c326584172428` |
| `backend/app/db/worker.py` | `28c6fd55fefae81791606d3225e04ac71a2cd7d8d6f2e5a296fbaedb67f7e474` |
| Unchanged `worker/runtime.py` | `fcb7a18e80a2e69174a4377d30b975ce86ccadfe3e8c58e3c7f8f32449db182f` |
| Unchanged benchmark script | `e7b17362e66e8a2a1ea9c3997f2f208ec8a313b5751f04daf04386b8912f513a` |

`control-paced.json` ran the f1d61c1 worker entrypoint/runtime. The subsequent
`no-busy-paced.json` ran the same code with only the busy-queue admission condition
changed from `count <= 20` to `count <= 0`; its temporary runtime SHA256 was
`29201476d63a6d555acecd7e0c40f1a968ac4bbe232e65de61fda8737cfcb30c`.
That experiment was restored byte-for-byte before the five pooled cells; no
busy-reference removal remains in the final source. The new, unused pool file
and tests were being prepared during controls but their old worker entrypoint
did not import/use them. Controls omit `--operations` and otherwise match a paced
cell exactly. Their JSON, including all raw samples, is retained separately.

## Correctness, operations and limits

All five pooled cells exited zero: 1,440 events and 1,980 correct unique effects,
zero missing effects, healthy charged retries, failed or unfinished PostgreSQL
deliveries after drain. Each maintenance initialize/rerun identity, rebuild and
before/after SQL reconciliation passed. The first cell also retains safe
status/inspect/repair/replay, original/replay identities, successful analytics
unchanged, forced stop, Redis content deletion/recovery and graceful exit zero.
Failure injection occurs after latency measurement; there is no outage guarantee.

New raw JSON was compared automatically with relay/original expectations for
script/hash, versions, migration head, workload, settings, event mix, final effects
and retained database counts. All matched. Stream length can differ because
successful cross-group execution can finish a delivery before a redundant
publication: it measures retained references, not runnable PostgreSQL work.
There is no pruning. All original evidence remains intact.

The [trace summary](benchmarks/worker-db-pool/trace-summary.json) retains aggregate
outcomes and approximate log stages for both controls and all five new cells,
without raw payloads or credentials. Busy outcomes do occur with the faster
pooled execution, and bounded revisits still resolve them without charged retries.
Fresh-control sink publication-observation to attempt-start P95 was 27.184s;
the three pooled paced runs show 0.195/0.200/0.196s. Attempt-start to completion-log
P95 falls from 0.309s to 0.028/0.028/0.027s. That second stage includes effect
transaction connection acquisition and is not a pure SQL/handler timing.
UI polling remains a separate 15-second cadence; dashboard reads remain live SQL.
External delivery, deployment, tracing, pruning and broader analytics are deferred.

See the [verification report](verification-milestone8-worker-db-pool.md) for final
gate results and the issue acceptance review. No M8 completion, merge or
application cutover follows from these local measurements.

## Measured distributions

All values below are seconds, nearest-rank conservative commit-to-receipt
visibility upper bounds. Proven misses require the lower bound above five
seconds; upper exceedances count all upper bounds above it. Pooled paced
percentiles are calculated from all samples, not averages of three percentiles.

| Load | Consumer | N | P50 | P95 | P99 | Max | Proven misses | Upper exceedances |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| paced-pooled | analytics | 240 | 0.938 | 1.639 | 1.72 | 1.779 | 0 | 0 |
| paced-pooled | alerts | 240 | 0.947 | 1.614 | 1.652 | 1.663 | 0 | 0 |
| paced-pooled | notification_sink | 840 | 0.997 | 1.687 | 1.81 | 1.864 | 0 | 0 |
| pressure | analytics | 80 | 1.142 | 1.655 | 1.848 | 1.848 | 0 | 0 |
| pressure | alerts | 80 | 1.177 | 1.674 | 1.827 | 1.827 | 0 | 0 |
| pressure | notification_sink | 280 | 1.39 | 1.794 | 1.988 | 2.009 | 0 | 0 |
| light | analytics | 40 | 0.925 | 1.654 | 1.814 | 1.814 | 0 | 0 |
| light | alerts | 40 | 0.91 | 1.606 | 1.658 | 1.658 | 0 | 0 |
| light | notification_sink | 140 | 1.004 | 1.726 | 1.889 | 1.889 | 0 | 0 |

The five-second target is met for every observed effect in this dataset,
including pressure. Worst conservative upper bound: 2.009s. This is a local
bounded-workload result, not a service-level or outage-time guarantee.

P95 comparison (analytics / alerts / sink), seconds:

| Version/cell | Analytics | Alerts | Sink |
|---|---:|---:|---:|
| Historical relay, three paced runs pooled | 3.952 | 6.293 | 37.125 |
| control-paced | 3.041 | 3.537 | 28.226 |
| no-busy-paced | 3.059 | 3.596 | 28.78 |
| paced-1 | 1.598 | 1.621 | 1.639 |
| paced-2 | 1.61 | 1.572 | 1.687 |
| paced-3 | 1.641 | 1.614 | 1.704 |
| paced-pooled | 1.639 | 1.614 | 1.687 |
| pressure | 1.655 | 1.674 | 1.794 |
| light | 1.654 | 1.606 | 1.726 |

Backlog samples count unfinished PostgreSQL deliveries. Oldest age comes from
the existing database-age probe; elapsed time includes production, not just
drain after production. Stream size includes completed/duplicate references.

| Cell | Peak unfinished | Peak oldest age s | Last drained elapsed s | Retained stream length |
|---|---:|---:|---:|---:|
| paced-1 | 11 | 1.835 | 79.608 | 440 |
| paced-2 | 11 | 1.845 | 79.655 | 440 |
| paced-3 | 11 | 1.826 | 79.568 | 440 |
| pressure | 43 | 2.015 | 21.318 | 439 |
| light | 11 | 1.878 | 77.277 | 220 |
| control-paced | 108 | 29.925 | 95.116 | 440 |
| no-busy-paced | 111 | 30.150 | 94.322 | 440 |
