# Event worker operations

## Scope

The T4 worker is a separate process that relays committed PostgreSQL event
deliveries into one Redis 7 Stream and keeps transport state recoverable. It does
not run with FastAPI and does not run Alembic. PostgreSQL is authoritative for
event facts, due times, claims, and delivery state. Redis contains minimal
references and pending transport messages.

The fixed consumer groups are `analytics`, `alerts`, and `notification_sink`.
T5 adds fenced consumer execution, receipts, bounded retries and operator
recovery. Issues #36–#37 install the analytics, alerts and notification-sink
handlers. Future valid contracts without a handler remain pending without
receipts or attempts.
Never interpret a publication observation or `XADD` reply as business processing.

Analytics inspection/reconciliation commands and the T8 maintenance interface are
documented in [the projection contract](../api/analytics-projection.md). Compare
one verified organization/restaurant pair before and after maintenance. A mismatch
can reflect an ordinary pending backlog; inspect analytics deliveries before
diagnosing corruption. Stop workers/quiesce writes before rebuilding, preserve
receipts and queued events, then reconcile and restart workers. Combined T8
initialization and operational rebuild CLI are documented in
[maintenance and backup/cutover procedures](event-maintenance.md).

## Start and stop

Configure the same `DATABASE_URL` and `REDIS_URL` used by the backend, then run
from `backend/`:

```powershell
.venv/Scripts/python.exe -m app.worker
```

```bash
.venv/bin/python -m app.worker
```

The worker opens its own bounded Redis pool. FastAPI neither starts nor depends
on it. Startup performs no migration and does not require Redis to be reachable
before the process is launched. Logs use the application's structured JSON
format and never include the Redis URL, payload, or raw driver exception.

Each `run_worker` invocation also owns a PostgreSQL connection pool on its own
event loop, disposed on exit. Its maximum is
`4 + EVENT_WORKER_RELAY_CONCURRENCY` (six by default), with no overflow and a
five-second checkout timeout. Three serial consumer loops, publication
observations and the recovery scan share this bound. Idle connections are checked
before reuse; failed checkouts follow the existing infrastructure retry policy.
Account for this per-process maximum when budgeting database connections across
workers. The API's test-only `NullPool` and production pool are unchanged.

Send Ctrl+C/SIGINT or SIGTERM for graceful shutdown. New loop iterations stop,
in-flight tasks receive up to `EVENT_WORKER_SHUTDOWN_GRACE_SECONDS` (10 seconds
by default), and remaining tasks are cancelled. If the process is forcibly
terminated, a PostgreSQL claim remains fenced until its lease expires (30 seconds
by default); a Redis pending message becomes reclaimable after its idle threshold
(60 seconds by default). Restarting a worker with the same settings resumes
recovery without manual database edits.

## Runtime budgets

All settings are typed `EVENT_WORKER_*` environment variables. Values below are
initial conservative defaults. Validation enforces that the Redis blocking read
fits inside the operation deadline, that the claim lease covers the bounded
number of relay deadline waves, and that maximum outage backoff is not shorter
than initial backoff.

| Setting | Default | Allowed range | Purpose |
|---|---:|---:|---|
| `EVENT_WORKER_CLAIM_BATCH_SIZE` | 10 | 1–100 | Maximum PostgreSQL deliveries claimed per relay batch. |
| `EVENT_WORKER_RELAY_CONCURRENCY` | 2 | 1–16 | Maximum concurrent publications in the batch. |
| `EVENT_WORKER_CLAIM_LEASE_SECONDS` | 30 | 1–600 | Ownership lease, based on PostgreSQL `now()`. |
| `EVENT_WORKER_RECOVERY_SCAN_INTERVAL_MS` | 1,500 | 1–60,000 | Idle relay wait and independent PostgreSQL recovery scan interval. |
| `EVENT_WORKER_RECOVERY_BATCH_SIZE` | 10 | 1–100 | Bound for group reads, pending scans, and stream-loss recovery per pass. |
| `EVENT_WORKER_REPUBLISH_STALL_SECONDS` | 60 | 1–3,600 | Delay before an observed but unfinished publication is eligible again. |
| `EVENT_WORKER_REDIS_BLOCK_MS` | 1,000 | 1–9,000 | Blocking `XREADGROUP` duration; must be below the operation deadline. |
| `EVENT_WORKER_REDIS_OPERATION_BUDGET_MS` | 2,000 | 1–10,000 | Outer deadline for each Redis operation, including pool acquisition. |
| `EVENT_WORKER_REDIS_MAX_CONNECTIONS` | 8 | 1–100 | Dedicated worker pool bound, independent of API Redis pools. |
| `EVENT_WORKER_PENDING_IDLE_MS` | 60,000 | 1–3,600,000 | Minimum idle time before reclaiming/rechecking any pending message, including the current worker's entries. |
| `EVENT_WORKER_INFRA_BACKOFF_INITIAL_MS` | 1,000 | 1–30,000 | First infrastructure retry/probe delay. |
| `EVENT_WORKER_INFRA_BACKOFF_MAX_MS` | 30,000 | 1–300,000 | Exponential outage-backoff cap; cannot be below the initial delay. |
| `EVENT_WORKER_MAX_ATTEMPTS` | 8 | 1–100 | Event-specific processing allowance per delivery retry cycle. |
| `EVENT_WORKER_SHUTDOWN_GRACE_SECONDS` | 10 | 1–120 | Grace period before loop cancellation and bounded pool close. |

The default lease covers five 2-second publication deadline waves for ten
deliveries at concurrency two, with room for the short claim transaction. Raising
batch size or lowering concurrency can require a longer lease. The 60-second
stalled-publication interval is intentionally much longer than the normal 1.5
second scan so transient Redis latency does not cause immediate republication.
The 60-second PEL idle threshold makes forced process recovery bounded while
avoiding immediate ownership churn. Tune only with workload and failure evidence.

## Recovery and failure behavior

The relay selects only due, unfinished subscribed deliveries in bounded batches
using row locks with `SKIP LOCKED`. It assigns each claim a unique token, owner,
and lease, commits, and then contacts Redis. Publication observation updates are
conditional on the same token and owner and an unexpired lease. A former owner
cannot change state after a newer claim takes over.

After a successful nonempty batch, the relay yields to other loops and checks
for another bounded batch immediately, including after a partial batch. It uses
the scan-interval wait only after an empty claim result. Batch size, publication
concurrency and leases remain unchanged. Publication failures still apply the
existing infrastructure backoff/cooldown; stop is checked between batches.
The existing expired-attempt recovery call still runs once per relay pass, so
it also runs more frequently during backlog. The independent recovery loop keeps
its configured scan interval.

If Redis stores an `XADD` but the response is lost, the delivery remains
recoverable. After lease or stalled-publication eligibility, a retry may create a
new Redis Stream ID carrying the same PostgreSQL event UUID. Infrastructure
failures use bounded loop backoff and a short persisted transport cooldown; they
do not consume a consumer's event-specific attempt allowance. `next_attempt_at`
in PostgreSQL remains authoritative, so an early Redis reference does not make a
delivery due.

Each consumer group advances independently. The worker creates absent groups
from the start of the stream. It scans bounded `XPENDING` pages and reclaims only
entries idle for the configured threshold using `XCLAIM`, including its own
entries. This revisits references that arrived before a due time or while another
attempt held the delivery lock, and eventually ACKs old references after completion.
The idle threshold and page limit bound repeated reads of unfinished work. Groups acknowledge
non-subscribed messages without effects.

For `delivery_missing_or_busy`, the current owner also revisits the original
pending reference after 50, 100, 200, then 250 ms, up to 20 revisits. Each revisit
reloads the reference only if the same Redis consumer still owns it and repeats
the normal PostgreSQL due/claim/receipt checks. One due busy reference is serviced
before each normal bounded pending/new-message pass; blocking reads shorten to
the nearest revisit deadline (or become nonblocking when already due).
At most `EVENT_WORKER_RECOVERY_BATCH_SIZE` busy references are held per group;
overflow or exhausted references stay pending for normal durable recovery.
These revisits create no processing attempts while the delivery remains locked.
Persisted failure deadlines, eight-attempt policy, infrastructure backoff and
abandoned-owner reclaim thresholds are unchanged.

PostgreSQL scans are the source of recovery after Redis connection failure or
content loss. The recovery loop logs stream length, group pending count, unfinished
deliveries and retained event/delivery/receipt/attempt counts. If the stream is
empty, it resets a bounded batch of old publication observations using a
PostgreSQL timestamp cutoff; due times are still enforced by the relay. Missing
groups are recreated idempotently. A Redis restart with stream loss therefore
republishes retained PostgreSQL events. No automatic stream trimming, event
deletion, or delivery-history cleanup runs.

The local development Redis has no persistence, so it may lose transport state
when restarted. That is expected: PostgreSQL reconstruction is the recovery path.
Do not use Redis `FLUSHDB`/`FLUSHALL` to simulate recovery; integration tests own
their isolated Redis service and namespace.

## Operational inspection

Worker recovery logs are named `event_worker_recovery_scan` and include safe
counts for stream size, pending entries, unfinished work and retained facts.
Publication and failure logs include event UUID, consumer, worker/claim identity,
correlation ID, safe failure category and outcome. They exclude event payloads,
credentials, Redis URLs and raw exceptions.

Run from `backend/` with trusted operator `DATABASE_URL` and `REDIS_URL`:

```bash
.venv/bin/python -m app.modules.events.cli status
.venv/bin/python -m app.modules.events.cli inspect DELIVERY_UUID
.venv/bin/python -m app.modules.events.cli replay DELIVERY_UUID --reason "Fixed the handler"
```

Use `.venv/Scripts/python.exe` on Windows. `--help` needs no database or secrets.
Commands return JSON. Status reports PostgreSQL pending/processing depth, oldest
unfinished age, unfinished event retries, failed and retained delivery/attempt/
receipt counts per consumer, retained event/replay counts, and Redis stream size.
A Redis outage gives `stream_size: null` and `redis_status: unavailable`; it does
not hide the database backlog. Pending includes unimplemented handlers. A retry
is unfinished work with an earlier charged attempt, not a Redis redelivery count.

Inspect accepts the delivery UUID (the `event_deliveries.id` column), not an
arbitrary actor or event selection query. It returns identity, scope, version,
correlation, status/due time, attempt history, receipt outcome, and replay
identities/provenance. It never prints event payloads, raw exceptions or free-form
replay reasons. `reason_recorded` confirms that a reason is retained; trusted
operators can inspect the retained reason directly in `event_delivery_replays`
when necessary. Do not put secrets or customer data in a replay reason.

The CLI's trust boundary is access to the operator environment and PostgreSQL
credentials with the necessary table privileges. It is not an HTTP endpoint and
accepts no `--operator`/Owner label as authority. Replay records PostgreSQL's
`session_user` (the authenticated connection role), a required reason, database
time, original correlation, and a generated replay UUID. Restrict those
credentials to trusted operators. Existing shared credentials identify a role,
not an individual human; provision distinct operator credentials when individual
attribution is required. No automatic role provisioning is introduced here.

Replay locks exactly one failed delivery with no receipt, increments its retry
cycle, resets its attempt allowance/due/publication/claim state, and commits the
provenance record atomically. It preserves the original immutable event/payload,
all earlier attempts/replays, and other consumers' receipts. Concurrent duplicate
replays, pending/successful targets, nonexistent targets and blank reasons are
rejected. Repair the handler before replaying; replay cannot rewrite a bad event.
No manual deletion of retained records is part of recovery.

## Backlog, failed work and Redis-loss incident sequence

1. Run `status` and retain its safe JSON with observation time and release revision.
   Compare per-consumer pending depth/oldest age, retries and failures over time.
   Stream size measures retained transport, not unfinished work; successful rows
   remain retained. A growing depth/age with available dependencies can indicate
   offered load above the configured relay/consumer capacity. Compare the
   documented measured workload before changing settings. A paused worker has no
   freshness guarantee.
2. If Redis reports unavailable, restore the configured Redis service and start
   the standalone worker; do not replay every pending row or reset its due times.
   PostgreSQL due/claim/recovery scans reconstruct unfinished subscriptions after
   content loss, recreate groups and retain the event UUID. Existing successful
   receipts remain authoritative. Observe falling PostgreSQL pending depth and
   each consumer's receipt outcomes, then reconcile analytics in the intended scope.
3. For a failed delivery, obtain its UUID from trusted database inspection and run
   `inspect DELIVERY_UUID`. Retain event/delivery/correlation, consumer, safe error
   category, cycle and attempts. Distinguish an unsupported contract, constraint
   failure, event transient failure and shared dependency outage. Repair the cause
   in reviewed code/configuration before replay; do not rewrite the immutable event.
4. Run `replay DELIVERY_UUID --reason "Reviewed handler repair"` once. Retain the
   returned replay UUID. Inspect again after recovery: the original event,
   correlation, earlier attempts and other consumers' receipts stay unchanged;
   only the selected failed consumer starts a new retry cycle. Repeated replay of
   pending/successful work must be rejected, not used to accelerate a backlog.
5. For graceful shutdown use Ctrl+C/SIGTERM and wait for zero exit. After a forced
   stop, restart and allow persisted claims/pending idle thresholds to expire;
   do not delete claims, receipts or attempts. Check final effects/receipts rather
   than interpreting an ACK or an empty stream as completion.

The [isolated executable rehearsal](../testing/event-freshness-benchmark.md)
retains these identities and per-consumer facts. Physical restart and precise
in-flight crash boundaries are exercised in the shared integration gate.
Never delete the developer Redis database/volume to rehearse a failure.

## Consumer execution details

A short transaction locks the delivery, checks its due time/receipt, allocates a
unique attempt and fenced lease, and records `processing`. A second transaction
locks that delivery, verifies the token and lease, calls a code-registered feature
handler, and commits the effect, unique receipt, attempt outcome and delivery
success together. Feature handlers participate in this service-owned transaction:
they must not commit/rollback or perform Redis/external I/O. T6/T7 install their
public transaction-bound feature interfaces in `events.execution.CONSUMERS`.
Returning `skipped` is a durable deliberate outcome; an unimplemented handler
cannot return a placeholder skip. Redis ACK runs after the effect commit.

Competing attempts skip a locked delivery; an old claim cannot overwrite a newer
one. Recovery uses bounded `SKIP LOCKED` scans for expired processing claims,
retains interrupted-attempt history and republishes pending work even after
complete Redis loss. Database locks protect an executing transaction even if its
lease expires while running; a replacement cannot acquire its delivery lock.
A crash before commit leaves no effect/receipt. A crash after commit leaves one
receipt and a subsequent reference only acknowledges it.

The default event-specific allowance is **eight attempts per retry cycle**.
Interrupted durably started attempts count, as agreed for T5. Retried transient
failures persist delays of 1, 2, 4, 8, 16, 32 and 60 seconds, plus uniformly sampled
0–10% positive jitter with the final delay capped at 60 seconds. Due times survive
worker restarts and remain authoritative against early Redis references. These
are minimum retry delays; scan/transport/outage delays can add latency.

Unsupported versions/invalid payloads and event-caused integrity violations fail
immediately with safe categories. Serialization/deadlock failures and other
handler failures use the bounded event allowance. No driver message is retained.
PostgreSQL connection/availability/resource SQLSTATEs, pool/network timeouts and
explicit shared-dependency failures use the existing 1–30 second bounded loop
backoff/probes. The failed attempt stays in history but its allowance is refunded.
Attempt history ordinals can therefore exceed eight; `attempt_count` measures the
charged allowance, not the number of retained diagnostic records. Successful
consumers remain untouched when another consumer fails.

If PostgreSQL is unavailable when recording an observed failure, the live worker
keeps that classification and retries settlement after reconnection before taking
new work. If the process also dies before it can persist that classification,
recovery can only observe a durably started interrupted attempt; the agreed crash
rule applies. Redis ACK failures occur after durable success and consume no new
attempt. Original correlation accompanies relay, execution and replay logs;
attempt UUID/ordinal/cycle and replay UUID extend the logging allowlist.

## Validation

For a reproducible isolated healthy-load measurement and actual CLI
failure/repair/replay/stream-loss/maintenance rehearsal, use
[the freshness procedure](../testing/event-freshness-benchmark.md).
Its [dated report](../milestone8/performance-milestone8.md) separates real misses,
observation uncertainty and UI refresh. It does not establish deployment capacity.

Worker behavior is covered by the `backend-unit`, `backend-integration`, and
`backend-static` gates. Integration tests use the repository's disposable
PostgreSQL 16/Redis 7 services and isolated Redis keys; they do not use the
persistent developer database volume. See
[`verification-milestone8-issue34.md`](../milestone8/verification-milestone8-issue34.md)
for historical T4 commands and environment limitations. T5 evidence is in
[`verification-milestone8-issue35.md`](../milestone8/verification-milestone8-issue35.md).
