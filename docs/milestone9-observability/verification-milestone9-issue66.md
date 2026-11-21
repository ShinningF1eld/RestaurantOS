# Issue #66 local verification

Verification date: 2026-11-20 ICT. Source base: `a3a53af`, plus the issue
working-tree changes. Each [runtime archive](evidence/issue66/) records exact
image IDs, configuration hashes, sanitized notification payloads and teardown.
See [issue #66](https://github.com/ShinningF1eld/RestaurantOS/issues/66) and
[the approved T8 thresholds](performance-milestone9-issue65.md#accepted-alert-settings-for-t9).

## Alerts and incident results

All six incident exercises passed across disposable instances of the real stack.

Prometheus qualifies all four operational conditions at the same 15-second
evaluation timestamp as their raw observations. Five consecutive eligible
observations cover a one-minute window and nine cover a two-minute window,
including both endpoints. A missing observation interrupts qualification.
Grafana uses distinct firing and recovery thresholds and a separate freshness
rule. The disposable local receiver captures grouped webhook payloads and
preserves the alert fingerprint across firing and resolution.

The API samples durable delivery age and depth independently of the worker.
The retry and timeout counters initialize at zero. The pinned Prometheus
tests cover first observations, counter reset, minimum traffic, freshness,
utilization, terminal work and missing worker telemetry. Process counters can
miss events before the first scrape, and window increases are estimates near
scrape boundaries.

| Exercise | Observed result |
| --- | --- |
| API failure | 440 faulted writes returned 500 and left no order. Loki and Tempo correlated the sanitized failure. The grouped alert fired once, resolved with its original fingerprint after the healthy window, and the authenticated session and existing durable effects remained consistent. [Evidence](evidence/issue66/api-failure-2026-11-20.json.gz) |
| Database exhaustion | PostgreSQL showed both connections blocked and the API pool reached 2/2. Readiness returned 503 in a 1.003-second API span. Loki and Tempo correlated the sanitized incident. Both reads and the existing login recovered. The grouped pool notification fired once and resolved. [Evidence](evidence/issue66/pool-monitoring-2026-11-20.json.gz) |
| Redis outage | Catalog reads fell back to PostgreSQL and login established a new authenticated session. Retained deliveries recovered after Redis restarted. The backlog alert resolved and 24 deliveries reconciled with 24 receipts and two stock consumptions across the worker and Redis exercises. [Evidence](evidence/issue66/worker-redis-2026-11-20.json.gz) |
| Worker stop | All three consumers fired on the database backlog while the worker was stopped. The firing backlog alert stayed active through an additional Collector gap. After restart the backlog and missing-source alerts resolved and 16 deliveries reconciled with 16 receipts. [Evidence](evidence/issue66/worker-redis-2026-11-20.json.gz) |
| Repeated job failure | Three scheduled retries preceded a terminal attempt. Repair and operator replay preserved the original event, delivery, correlation and attempt history. One new attempt succeeded and 16 deliveries reconciled with 16 receipts, one completed order and one stock consumption. The rule fired once and resolved. [Evidence](evidence/issue66/repeated-job-2026-11-20.json.gz) |
| Monitoring outage | Collector, Loki/Tempo and Grafana outages each allowed orders and worker effects to complete. With the Collector offline, the API and worker shut down cleanly in 5.203 and 4.078 seconds, then restarted and reconciled. The run retained scrape loss and recovery, 15 failed log records, 23 failed spans and bounded queues. All 40 deliveries reconciled with 40 receipts across four completed orders, and no container was OOM-killed. [Evidence](evidence/issue66/application-shutdown-2026-11-20.json.gz) |

The intentional failure returned a failure exit status, retained its safe report
and removed owned resources. The live runs used unique databases, random
ports and disposable containers. They captured no browser auth traces and sent
all notifications to the private local receiver. [Cleanup evidence](evidence/issue66/cleanup-2026-11-20.json.gz).

The [incident runbook](../runbooks/local-incidents.md) covers API errors,
pool exhaustion, Redis, backlog, repeated jobs, monitoring loss, failed
migration and compatible rollback. It reuses the verified backup and quiescence
procedures. There was no application database migration or public API/schema
change. Hosted alerting and rollback require separate verification.

The supplied engineering notes retain a PostgreSQL rate-limit description.
The current authentication implementation uses Redis admission and a
process-local fallback, and PostgreSQL remains authoritative for sessions.
The Redis exercise checked the current contract. [Authentication runbook](../runbooks/authentication.md#limiter-outage-and-recovery-operations).

## Validation commands

From the repository root using the Python 3.12.13 observability environment:

```powershell
backend/.venv-observability/Scripts/python.exe scripts/check-monitoring-config.py
backend/.venv-observability/Scripts/python.exe scripts/check-alert-rules.py
backend/.venv-observability/Scripts/python.exe scripts/validate.py --gate baseline --gate backend-static --no-install
backend/.venv-observability/Scripts/python.exe scripts/validate.py --gate backend-static --gate backend-unit --no-install
backend/.venv-observability/Scripts/python.exe scripts/validate.py --gate browser --gate image --no-install
backend/.venv-observability/Scripts/python.exe scripts/validate.py --gate image --no-install
```

The pinned configuration parsers, native rule tests, baseline, static checks
and 529 unit tests passed. Browser evidence includes 29 host Chromium
journeys, 15 HTTPS gateway cases and both intentional failure probes. Both
production images passed. All four existing dashboards loaded in the
disposable Grafana instance. The gates reused installed locks. See the
[incident commands](../testing/monitoring.md#local-alerts-and-incident-verification-66)
for the runner and its individual case selectors.

The broader backend integration command was:

```powershell
backend/.venv-observability/Scripts/python.exe scripts/validate.py --gate baseline --gate backend-integration --gate browser --gate image --no-install
```

That run stopped at integration with 370 passed, 9 failures, 1 expected
opt-in skip and 1 teardown error. The focused rerun passed both Redis
assertions and the cleanup that previously timed out. The business metrics
assertion passed with the optional developer aggregate sampler disabled, as its
fixture expects. The remaining six worker subprocess cases also failed on an
untouched archive of `a3a53af` under the same Windows interpreter using the
original test support and freshly migrated disposable databases.
