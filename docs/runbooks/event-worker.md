# Event worker operations

## Scope

The T4 worker is a separate process that relays committed PostgreSQL event
deliveries into one Redis 7 Stream and keeps transport state recoverable. It does
not run with FastAPI and does not run Alembic. PostgreSQL is authoritative for
event facts, due times, claims, and delivery state. Redis contains minimal
references and pending transport messages.

The fixed consumer groups are `analytics`, `alerts`, and `notification_sink`.
T4 acknowledges a group's message only when that consumer is not subscribed to
the event. Subscribed messages remain pending: T5 must add the business effect,
durable receipt, delivery completion, and then the Redis acknowledgement. Do not
interpret a publication observation or an `XADD` reply as business processing.

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
| `EVENT_WORKER_RECOVERY_SCAN_INTERVAL_MS` | 1,500 | 1–60,000 | Relay and PostgreSQL recovery scan interval. |
| `EVENT_WORKER_RECOVERY_BATCH_SIZE` | 10 | 1–100 | Bound for group reads, pending scans, and stream-loss recovery per pass. |
| `EVENT_WORKER_REPUBLISH_STALL_SECONDS` | 60 | 1–3,600 | Delay before an observed but unfinished publication is eligible again. |
| `EVENT_WORKER_REDIS_BLOCK_MS` | 1,000 | 1–9,000 | Blocking `XREADGROUP` duration; must be below the operation deadline. |
| `EVENT_WORKER_REDIS_OPERATION_BUDGET_MS` | 2,000 | 1–10,000 | Outer deadline for each Redis operation, including pool acquisition. |
| `EVENT_WORKER_REDIS_MAX_CONNECTIONS` | 8 | 1–100 | Dedicated worker pool bound, independent of API Redis pools. |
| `EVENT_WORKER_PENDING_IDLE_MS` | 60,000 | 1–3,600,000 | Minimum idle time before reclaiming another consumer's pending message. |
| `EVENT_WORKER_INFRA_BACKOFF_INITIAL_MS` | 1,000 | 1–30,000 | First infrastructure retry/probe delay. |
| `EVENT_WORKER_INFRA_BACKOFF_MAX_MS` | 30,000 | 1–300,000 | Exponential outage-backoff cap; cannot be below the initial delay. |
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

If Redis stores an `XADD` but the response is lost, the delivery remains
recoverable. After lease or stalled-publication eligibility, a retry may create a
new Redis Stream ID carrying the same PostgreSQL event UUID. Infrastructure
failures use bounded loop backoff and a short persisted transport cooldown; they
do not consume a consumer's event-specific attempt allowance. `next_attempt_at`
in PostgreSQL remains authoritative, so an early Redis reference does not make a
delivery due.

Each consumer group advances independently. The worker creates absent groups
from the start of the stream. It scans bounded `XPENDING` pages and reclaims only
entries owned by another consumer and idle for the configured threshold using
`XCLAIM`. A restarted consumer therefore recovers abandoned PEL work without
repeatedly routing its own pending subscribed messages. Groups acknowledge
non-subscribed messages without effects.

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

Use Redis `XLEN` and `XINFO GROUPS` against the configured namespaced stream to
inspect transport depth and each group's pending count. PostgreSQL
`event_deliveries` remains the authoritative unfinished-work view. Issue #35
owns the operator status/inspect/replay CLI; manual database edits or deletion
of retained event records are not part of this runbook.

## Validation

Worker behavior is covered by the `backend-unit`, `backend-integration`, and
`backend-static` gates. Integration tests use the repository's disposable
PostgreSQL 16/Redis 7 services and isolated Redis keys; they do not use the
persistent developer database volume. See
[`verification-milestone8-issue34.md`](../milestone8/verification-milestone8-issue34.md)
for the dated commands and environment limitations.
