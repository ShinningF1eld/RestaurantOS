# Milestone 8 Issue #34 / T4 verification

Date: 2026-10-12 (Asia/Bangkok).
Authority: [approved revision 1 design](milestone-8-design.md).
Issue: [#34](https://github.com/ShinningF1eld/RestaurantOS/issues/34).
Base: `fb93d270bec765abe0bc7c57abb83cac8548e94d` (`main` at task start); work
was performed on `feature/m8-issue-34-worker`.

## Scope and decisions

Added a standalone `python -m app.worker` runtime with one relay loop, one
PostgreSQL recovery loop and one reader for each fixed Redis consumer group.
PostgreSQL remains the source of event facts, due times, claims and unfinished
delivery state. The worker owns an independent bounded Redis connection pool;
the API cache/auth adapter and its 100 ms timeout and failure policies were not
changed. Redis Stream entries contain only event UUID, event type, schema
version and correlation ID. A republish preserves the PostgreSQL UUID while
Redis assigns a new Stream ID.

Delivery claims use short transactions, due-time selection, `FOR UPDATE SKIP
LOCKED`, unique claim tokens, leases and conditional ownership-fenced updates.
The claim commits before Redis I/O. Successful `XADD` records only a publication
observation; it never completes a subscribed delivery. The transport does not
implement Issue #35's business effects, receipt transaction, event retry policy
or replay CLI. Subscribed references remain pending for that work. Non-subscribed
groups acknowledge after PostgreSQL validates the event and fixed registry.

Recovery uses bounded PostgreSQL batches, idempotent group creation, paged
`XPENDING` plus `XCLAIM` for abandoned entries, and PostgreSQL reconstruction
when stream content is lost. PostgreSQL time is used for persisted lease and due
comparisons. Infrastructure failures pause affected loops with bounded backoff
and do not increment consumer attempt counts. No schema/migration, API, image,
dependency, frontend or developer Redis persistence changes were made.

The chosen defaults and ranges are in the [event worker runbook](../runbooks/event-worker.md).
The 10-row claim batch with concurrency two fits five 2-second Redis deadline
waves inside a 30-second lease. Recovery scans every 1.5 seconds in batches of
10. Republishing after an observed stall waits 60 seconds; PEL reclaim waits for
60 seconds of idle time. Outage backoff doubles from 1 to 30 seconds. The
dedicated pool is capped at eight connections and shutdown grace is 10 seconds.
Settings validate the relationships between those limits.

## Acceptance review

| Issue criterion | Evidence |
|---|---|
| Redis 7 stream references, independent groups and PostgreSQL validation | `integration/test_event_worker.py::test_real_worker_entrypoint_relays_reference_and_shuts_down_gracefully` checks the exact four minimal fields. `test_consumer_groups_route_independently_reclaim_own_pel_and_rebuild_stream` checks analytics/sink delivery, alerts non-subscription acknowledgement, independent PEL ownership and recovery. `unit/test_event_worker.py` checks the groups against the fixed registry. |
| Bounded, fenced delivery claims and documented budgets | `test_two_claimants_expiry_and_old_claim_fencing` synchronizes two claimants with a barrier, expires the winning claim and proves the old token cannot update after a newer owner takes over. `test_relay_claim_batch_stays_bounded_with_significant_backlog` claims exactly 10 of 25 due events. Config unit tests reject unsafe deadline, lease, batch and backoff relationships. |
| Publication observation and bounded recovery | The real-process crash tests stop after PostgreSQL claim and after `XADD` before observation; restart recovers the original event UUID and leaves delivery status pending with zero consumer attempts. Group and physical Redis restart tests recreate lost stream/groups from PostgreSQL. Recovery logs stream size, PEL depth, unfinished deliveries and retained event/delivery/receipt/attempt counts. |
| Ambiguous transport, retry due times and stale ownership | Crash after XADD produces a second Stream ID with the same event UUID. The early-reference test leaves a subscribed item pending until stored `next_attempt_at` is due. The barrier claim test checks expiry and ownership fencing. Redis outage/recovery preserves the event attempt count. |
| Separate worker lifecycle and API/worker Redis isolation | The actual worker entrypoint relays and shuts down gracefully; other process tests forcibly kill and restart it. The independent pool unit test verifies worker deadline/pool size separately from the API's 100 ms/20-connection pool. `worker.py` starts no FastAPI app and runs no Alembic command. |
| Retained work visibility and no automatic deletion/trimming | Recovery scan records stream, pending, unfinished and retained counts. Code and documentation add no stream trimming or event/history deletion. The 25-event backlog test proves the claim boundary is bounded. |

T4 intentionally leaves subscribed messages in the PEL and PostgreSQL delivery
rows unfinished until Issue #35 commits effect and receipt handling. These tests
establish transport recovery, not downstream business effects or full M8
acceptance. Independent verification remains pending.

## Commands and outcomes

The host used `backend/.venv/Scripts/python.exe`, Python 3.13.15. Python 3.12 is
the supported baseline but was not installed on this host. Commands ran with
committed installed dependencies; locked dependency installation was omitted.

```powershell
backend\.venv\Scripts\python.exe scripts\validate.py --gate backend-unit --no-install
backend\.venv\Scripts\python.exe scripts\validate.py --gate backend-integration --no-install
backend\.venv\Scripts\python.exe scripts\validate.py --gate backend-static --no-install
Push-Location backend
.venv\Scripts\python.exe -m pytest tests\unit\test_event_worker.py -q
Pop-Location
```

- `backend-unit`: passed, 270 tests. The sandboxed attempt stalled during the
  first async auth test; rerunning the pure gate outside the restricted process
  environment passed. This was an environment limitation, not a passing result
  from the interrupted run.
- `backend-integration`: passed, 268 tests with real disposable PostgreSQL 16
  and Redis 7 processes. The runner applied migrations only to its uniquely
  named disposable database, `alembic check` found no model drift, and the owned
  Compose services were removed. The first sandboxed launch could not access the
  Docker API; the same command succeeded with Docker access enabled.
- `backend-static`: passed Ruff lint, Ruff format and mypy (139 source files).
- Focused worker unit module: passed, 8 tests.

An initial static run identified one Ruff formatting adjustment in the worker
runtime; it was formatted and the final static gate passed. The two initial
integration synchronization failures were corrected by waiting for all groups'
delivery cursors and the PostgreSQL publication observation; the final full
integration gate then passed. Those failed attempts are not acceptance evidence.

Omitted: baseline, frontend-static/tests/build, browser, separate `migrations`,
image, locked reinstall and final PR CI. There were no frontend, schema, metadata,
or image changes; integration performed clean disposable upgrades and `alembic
check`. The developer database and persistent Compose volume were not migrated
or modified. This issue report does not claim full Milestone 8 acceptance.
