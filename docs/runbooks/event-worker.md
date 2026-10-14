# Event worker operations

## Scope

The T4 worker is a separate process that relays committed PostgreSQL event
deliveries into one Redis 7 Stream and keeps transport state recoverable. It does
not run with FastAPI and does not run Alembic. PostgreSQL is authoritative for
event facts, due times, claims, and delivery state. Redis contains minimal
references and pending transport messages.

The fixed consumer groups are `analytics`, `alerts`, and `notification_sink`.
T5 adds fenced consumer execution, receipts, bounded retries and operator
recovery. Issue #36 installs the analytics handler. Alert and sink handlers remain
Issue #37; valid deliveries without a handler remain pending without receipts or attempts.
Never interpret a publication observation or `XADD` reply as business processing.

Analytics inspection/reconciliation commands and the T8 maintenance interface are
documented in [the projection contract](../api/analytics-projection.md). Compare
one verified organization/restaurant pair before and after maintenance. A mismatch
can reflect an ordinary pending backlog; inspect analytics deliveries before
diagnosing corruption. Stop workers/quiesce writes before rebuilding, preserve
receipts and queued events, then reconcile and restart workers. Combined T8
initialization and operational rebuild CLI remain pending.

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

## Consumer execution and retries

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

Worker behavior is covered by the `backend-unit`, `backend-integration`, and
`backend-static` gates. Integration tests use the repository's disposable
PostgreSQL 16/Redis 7 services and isolated Redis keys; they do not use the
persistent developer database volume. See
[`verification-milestone8-issue34.md`](../milestone8/verification-milestone8-issue34.md)
for historical T4 commands and environment limitations. T5 evidence is in
[`verification-milestone8-issue35.md`](../milestone8/verification-milestone8-issue35.md).
