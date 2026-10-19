# Event processing freshness measurement

Run from the repository root with the supported Python 3.12 environment, Docker
Desktop and committed dependencies. The runner starts a unique Compose project
with random loopback ports, allocates a guarded `_test` database, migrates only
that database and runs the production `python -m app.worker` process. It drops
the allocated database and owned services on exit. It never reads the application
database URL as a test target. Do not point it at developer services.

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-event-freshness.py --bundles 40 --rate 0.5 --concurrency 4 --operations --output test-results/issue41-healthy-1.json
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-event-freshness.py --bundles 40 --rate 0.5 --concurrency 4 --output test-results/issue41-healthy-2.json
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-event-freshness.py --bundles 40 --rate 0.5 --concurrency 4 --output test-results/issue41-healthy-3.json
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-event-freshness.py --bundles 40 --rate 2 --concurrency 4 --timeout 240 --output test-results/issue41-pressure.json
backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-event-freshness.py --bundles 20 --rate 0.25 --concurrency 4 --output test-results/issue41-light.json
```

Use the equivalent venv interpreter on Unix. Run cells sequentially without
validation/builds/other benchmarks competing for the host. Repeat on a target
machine before making capacity claims. `--help` describes bounded workload
parameters. Worker tuning uses the defaults selected by the shared isolated
service environment, including 10 deliveries/claim, two concurrent publications,
1,500 ms scans, 30-second leases, 60-second stalled publication/reclaim and eight
processing attempts. Every selected `event_worker_*` setting is retained in JSON.
There is one worker, with one serial execution loop per consumer group.

## Dataset and interpretation

Each scheduled bundle commits six synthetic typed order/menu event fixtures in
one transaction: submitted, accepted, completed, cancelled, deleted and menu
edited. The completed order has a real authoritative COMPLETED row worth 12.50;
the deleted identity is absent, exercising its tombstone. The other snapshots
represent committed facts without exercising the HTTP/order lifecycle. A second
transaction uses the production inventory creation service with a real active
Owner membership, authorization, restaurant lock, opening movement and audit. It
creates one ingredient at quantity 1 g/threshold 5 g, emitting state-changed and
low events plus authoritative episode facts. The ingredient stays low throughout
the measurement. No fabricated historical episodes or notifications are seeded.

Eight events fan out to eleven subscribed deliveries per bundle: two analytics,
two alerts and seven notification-sink deliveries. Forty bundles produce 320
events, 440 receipts, 40 completed orders, 40 low ingredients/episodes/stubs and
240 diagnostics, with 500.00 completed sales. One organization/restaurant and a
single UTC creation date deliberately exercise shared projection rows/locks.
This is a small delivery/projection workload, not a full API throughput or large
dataset benchmark. At 0.5 bundles/s the scheduled rate is four events/5.5
deliveries per second; at two bundles/s it is 16 events/22 deliveries per second.
`--concurrency` bounds simultaneous producing bundles; it is not a claim that all
slots remain occupied at a paced low rate. Host delays and service locks can lower
the achieved rate. Raw backlog elapsed times and sample counts remain available.

No measured event is a warm-up discard. Infrastructure/group startup precedes
the sample; newly committed work is measured through drain. Use the same command
for a fresh database each time. The JSON records script version/SHA256, repository
HEAD (uncommitted implementation is disclosed in the report), platform, Python,
PostgreSQL, Redis, migration head, settings, event mix and every subscribed sample.

## Timing and target misses

The pressure run allows 240 seconds to drain after its scheduled production span;
other runs use 120 seconds. This watchdog does not change worker due times,
claims, retries or the five-second target. It allows a growing queue and the
default 60-second pending/stall recovery to finish before a missing-effect error.

The additional light check uses 20 bundles at 0.25/s (two events/2.75 deliveries
per second) and half the dataset, and is reported separately rather than replacing
the original three paced repetitions. "Healthy" in retained filenames describes
available dependencies; it does not assert that the five-second target passed.

The observer reads committed receipts on an independent READ COMMITTED session.
The effect, receipt and delivery success share the consumer transaction, so receipt
visibility proves durable completion. `occurred_at`, `recorded_at` and receipt
`processed_at` are not commit timestamps and are not used for latency.

One host monotonic clock brackets the producer's COMMIT using SQLAlchemy's
`before_commit` and `after_commit` hooks after explicit producer flushes. Receipt
observation is bounded by the preceding query's start (when the receipt was
absent) and the first query result containing it. Therefore:

- `upper_ms`: first visibility minus the producer's pre-COMMIT mark. It includes
  producer commit acknowledgement and observation overhead conservatively.
- `lower_ms`: preceding absent-query start minus producer commit acknowledgement,
  clamped to zero. A fast consumer can finish before that acknowledgement.
- Both commit/observation bracket widths are retained per sample. The requested
  25 ms polling interval is a minimum wait, not a guaranteed observation accuracy;
  SQL/network/event-loop delays widen the observed bracket.

P50/P95/P99 use nearest-rank **upper bounds** per subscribed consumer. Lower-bound
distributions are also retained. `over_5000_ms` reports upper-bound exceedances;
`certain_over_5000_ms` counts lower bounds above five seconds, proving real misses.
Their difference is measurement uncertainty around the target. Missing/failed
effects are explicit and cause nonzero exit; they never become zero-latency
samples. Target misses do not cause nonzero exit: measuring a miss is valid
evidence. The runner also checks expected effects, exact totals, graceful exit,
scoped reconciliation and initialization rerun identity.

Backlog depth/oldest age/failures are sampled through drain; status supplies
per-consumer retries, failures, retained deliveries/attempts/receipts, global
events/replays and Redis stream length. Counts before maintenance are separated
from later maintenance and failure-rehearsal writes. No pruning occurs. This is
healthy worker freshness, separate from the inventory page's visible 15-second
refresh. No outage-time freshness guarantee is claimed.

## Operator rehearsal

`--operations` adds a separate post-measurement scenario after stopping healthy
production. It uses a new completed order/event, processes analytics once, and
injects a test-only constraint-failing sink into the execution service. The normal
eight-attempt policy is unchanged; a permanent constraint failure is immediately
retained. It invokes the actual CLI `status`, `inspect` and `replay` with a safe
repair reason. A production worker is forcibly killed with queued work; only the
owned stream key is deleted, then a production worker recreates groups and
recovers the original event. The output preserves before/after event, delivery,
correlation, replay UUID, database-role provenance and both consumer histories.
Analytics must still have one attempt. Graceful recovery exit must be zero.

This forced stop is a queued-work rehearsal, not evidence of a particular
in-flight crash boundary. Required integration suites cover actual barriers
before/after effect commit, real poison backoff restart, ambiguous XADD/XACK and
physical Redis restart. See [the regression map](milestone8.md).
Every run also invokes real CLI reconciliation, initialization/rerun, rebuild and
reconciliation with writers/workers stopped; these do not enter latency samples.
Backup/restore is rehearsed by the migration gate, not by this measurement.

Retain reviewed JSON in `docs/milestone8/benchmarks/`. Worker logs stay in ignored
`test-results/`; they contain safe event/attempt/correlation metadata. Never retain
environment dumps, URLs with credentials, customer payloads or authentication traces.
See [measured evidence](../milestone8/performance-milestone8.md).
