# Local incident response

Use the Grafana **RestaurantOS local incidents** group and its linked operator
dashboards. Save the alert name, source or role/slot/consumer, onset and recovery
times, and the release and actual database revision. Use a request ID, trace ID
or delivery UUID to follow individual operations. Keep credentials, raw exception
text, SQL parameters, customer data and auth traces out of incident evidence.

The [approved thresholds](../milestone9-observability/performance-milestone9-issue65.md#accepted-alert-settings-for-t9)
are evaluated every 15 seconds. Prometheus qualifies observations at the same
evaluation timestamp as the raw samples. It requires five consecutive
observations for a one-minute window, or nine for a two-minute window, including
both endpoints. Grafana consumes those results. An ineligible observation
interrupts either window. An active incident stays active through a deadband,
missing observations or a Prometheus query error. The separate missing-telemetry
rule reports collector, API, delivery sampler and worker freshness after one
minute. API freshness tracks request activity, so an idle API can report an
unknown signal. Check `ros_alert:api_eligible_5m` to distinguish low traffic
from a stale observation. An unconfigured pool slot remains unknown.

Grafana groups by alert name and operational identity. The first group waits 5
seconds, group changes dispatch at 15-second intervals, and unchanged firing
groups repeat after 30 minutes. The local webhook sends resolutions. The
receiver runs on the private monitoring network during the disposable exercise,
with no published port or outbound delivery. Standard local monitoring can
show rule state in Grafana. The local webhook has no receiver until the capture
container is running.

### API errors

1. Compare eligible request volume, unexpected server errors and the Service
   Overview breakdown. Health/readiness, expected client errors and cancellations
   are outside the error ratio. Low traffic leaves the ratio unknown.
2. Match normalized route, request ID and trace ID in Loki and Tempo. Confirm
   whether an affected write committed before retrying it. Preserve the original
   idempotency key when the outcome is uncertain.
3. Remove the fault or restore a compatible release. Confirm the route and an
   existing session still work, reconcile order/stock/audit/outbox state, and
   observe the recovery window and resolved alert.

### Database exhaustion

1. Check `/health` and bounded `/ready` separately. In **Database & Redis**,
   identify the affected API or worker-slot pool. Compare used/limit, acquisitions,
   timeouts and slow queries. An acquisition in progress can include pre-ping
   and connection setup as well as time waiting for the pool.
2. Inspect PostgreSQL activity and `pg_blocking_pids(pid)` for the intended
   database. Identify the owning transaction, age and blocking chain. Quiesce
   affected admission or workers if pressure is compounding. Release the blocker
   through its owner or the operator's approved database procedure. Avoid raising
   pool capacity before checking the PostgreSQL connection budget.
3. Check that checked-out sessions return, readiness and authenticated requests
   succeed, and affected writes reconcile. Wait for fresh utilization below 60%
   and the timeout lookback to clear before counting the two-minute recovery.

### Redis outage

1. Confirm Redis failures and bypasses in **Database & Redis**. Test authorized
   catalog reads against existing [cache fallback rules](redis-cache.md).
   PostgreSQL remains authoritative for sessions and business state. Confirm
   order writes and independent worker status with `app.modules.events.cli status`.
2. Restore the intended Redis service and observe the worker republish eligible
   PostgreSQL work and recreate its consumer groups. Keep delivery IDs, due times
   and receipts intact. Follow the [worker Redis-loss sequence](event-worker.md#backlog-failed-work-and-redis-loss-incident-sequence).
3. Verify the previously unfinished deliveries and projections reconcile. Compare
   cache bypass, worker depth and oldest age before and after recovery.

### Queue backlog

1. Compare per-consumer depth and age for queued, in-flight, retry-delayed and
   recovery-due deliveries. The alert sampler reads PostgreSQL independently of
   the worker. Query `ros_alert:unfinished` and `ros_alert:unfinished_age` in
   Grafana Explore, including while the worker is offline. Stream length or an
   ACK alone cannot establish completion.
2. Check whether the worker is running and whether PostgreSQL and Redis are
   reachable. Restore the worker on its assigned slot. Allow existing leases and
   retry deadlines to elapse. See [worker recovery](event-worker.md#recovery-and-failure-behavior).
3. Verify eligible work produces one receipt and effect per subscribed consumer,
   then observe recovery with oldest age below five seconds or fresh zero depth.

### Repeated job failure

1. Use the [worker CLI](event-worker.md#operational-inspection) to inspect the
   affected delivery UUID. Record its event, consumer, original correlation,
   cycle, retry history, category, terminal status and other consumers' receipts.
2. Repair the handler or dependency in reviewed code or configuration. Replay
   the repaired failed delivery once via the trusted operator CLI. Preserve the
   immutable event. Capture the replay UUID and the old and new attempts.
3. Reconcile durable effects and verify the intervening successes remain unique.
   Observe a fresh zero terminal count and the recovery window after retry counts
   drop below three. A new process needs an observed counter baseline. Events
   between two scrapes can be recovered from the durable attempt log when the
   process counter resets before Prometheus samples those events.

### Monitoring outage

1. Check Collector scrape availability, source ages, destination health and
   available exporter failures or refused signals. A successful scrape can still
   contain old application data. The Collector expires unrefreshed series after
   30 seconds. Unavailable metrics and known zero values are distinct.
2. Check business health via API readiness and worker CLI or PostgreSQL evidence.
   The SDK uses bounded queues, export deadlines and shutdown waits. The
   Collector's memory limiter and bounded sending queues may drop telemetry
   while stores are unavailable. Current-process counters and bounded local logs
   provide partial loss evidence. Complete replay of traces and logs is unavailable.
3. Restore failed components and check new metric timestamps, logs and traces.
   Inspect range queries across the observed gap. During Grafana downtime,
   Grafana-managed evaluation, state updates and webhook delivery stop even
   when Prometheus is still recording. After restart, inspect available
   Prometheus history. A brief firing/resolution that happened entirely during
   Grafana downtime may have no notification or Grafana state transition.

### Failed migration

1. Keep writers and workers quiesced. Record the release revision, migration
   revision actually reported by the database, failing step and whether its
   transaction committed. Check remaining sessions and locks before attempting a
   repair. Use the [maintenance and verified-backup procedure](event-maintenance.md).
2. Reproduce the failure with a verified restore in a newly owned test database.
   Review the migration and data constraints. Confirm expected revision, data
   fingerprints and Alembic drift after repair in that database.
3. Resume an explicitly approved migration only after the repair and restore
   route are verified. If commit state is uncertain, inspect it before retrying.
   Preserve order snapshots, balances, ledgers, outbox, receipts, attempts and
   replay provenance. Reconcile before reopening writes.

### Compatible rollback

1. Before reverting binaries, check actual schema and event compatibility in
   both directions, including pending event versions, immutable facts and
   consumers' ability to process them. Maintain the same quiescence and verified
   backup requirements used for migration.
2. Rehearse the prior binaries against a disposable copy at the actual revision.
   Roll back binaries with the schema retained when proven compatible. A schema
   downgrade requires its own review and approval. A downgrade guard that rejects
   existing history is a reason to stop and choose a reviewed recovery path.
3. Check readiness, authorization, committed totals, stock ledger and durable
   delivery effects before restarting request admission. A restore can discard
   writes after its recovery point. Use the
   [maintenance rollback boundaries](event-maintenance.md#interruption-rerun-and-analytics-reconstruction)
   when selecting a recovery point. This runbook covers local exercises. Hosted
   traffic, backup and rollback behavior require separate verification.
