# Issue #61 — PostgreSQL and Redis diagnostics

Public base Git revision: `e65671d9b7fe80707873a5e52b9d7912de00def0`. <!-- pragma: allowlist secret -->

Date: 2026-11-03 (Asia/Bangkok). Scope: local issue #61 implementation and isolated
verification; no commit, PR, issue mutation, schema migration or developer-data
operation. No dependency pins, business URLs or frontend implementation changed.

The [operational contract](../../monitoring/database-redis.md) records exact names,
units, source versions, grants, cadence, timeout/measurement limitations, setup
and staleness. The [testing guide](../testing/monitoring.md#postgresql-redis-and-pools-61)
records reproduction commands. Evidence below applies to this working tree,
not a published revision or full M9 acceptance.

## Acceptance mapping

| Issue criterion | Implementation and evidence |
|---|---|
| SQL duration/slow/failures, pools, transaction rollback semantics | Engine events on sync_engine, transparent public pool connect boundary, per-process SDK instruments; actual API/worker pooled subprocess regressions. Read teardown is excluded; repeated aborted statements count one failed transaction; deferred commit errors are classified. |
| Real pools, overlap and safe SQL | Two independent processes use production engine factories, synchronize acquisitions inside a full queue, timeout/cancel/recover, and inspect actual SDK metrics. Compiled operation flags only; SQL/parameters/canaries do not become attributes. |
| Read-only PostgreSQL collection with minimum grants | Pinned receiver configured for one database, one collector connection, bounded stats queries and no table/query/history sampling. Dedicated LOGIN has no elevated memberships; required statistics reads succeed and business/administrative operations fail. |
| Redis/cache diagnostics with distinct semantics | Generic API/worker transports preserve budgets and driver classifications; catalog owns exactly-one hit/miss/bypass decision after authorization/live stock checks. Restricted INFO-only receiver exports server memory/evictions and aggregate statistics. |
| Exact mappings/resource cost/privacy | Complete allowlists and operational tables, pinned binary configuration checks, actual Prometheus queries/canary exclusion and rounded Docker resource samples. Grafana retains only its three existing data sources. |
| Unavailable collection, staleness/recovery, contract preservation | Isolated pause/unpause and Collector-absent workloads require missing receiver series, observed scrape failures, resumed stored metrics and successful DB/Redis work under existing limits. Existing cache/auth/outbox/order/inventory/audit integration suites remain required. |

## Retained failed attempts

The initial environment lacked the already committed OTel packages; installing
`backend/requirements-dev.txt` with `--require-hashes` restored the lock exactly.
No dependency source/lock changed. An initial static run before installation failed
on missing imports; a diagnostics/audit function-name collision was corrected.

Initial unit fixtures used a wall clock inconsistent with the real catalog service's
payload timestamp and therefore missed every payload; the fixture was corrected,
without changing production freshness policy. Existing pipeline-set assertions
were extended to include the new independent metrics pipeline.

The first receiver parser attempt grouped a metric-only aggregation with datapoint
statements; explicit OTTL contexts fixed the rejected configuration. A first outage
harness stopped the disposable tmpfs PostgreSQL process, losing the temporary
cluster and invalidating recovery/admin teardown. Subsequent rehearsals use
pause/unpause and always unpause before cleanup. These failures are not passing
acceptance evidence and did not touch developer resources.

Stored checks additionally detected an incorrect pool-gauge Prometheus query: the
pinned exporter translates gauge unit `1` to a `_ratio` suffix. Connection gauges
now use the truthful `{connection}` unit, with stored names verified on the native
exporter. Collector guards were also hardened to test the metric family before
optional attributes. Parser success alone was insufficient; final verification
inspects stored pool signals, not only the SDK or admitted OTLP payload.

## Compatibility boundaries

SQLAlchemy has no public queue-waiter count. `pool.acquiring` includes connect and
pre-ping and is labeled accordingly; NullPool provides no fake pool capacity.
The Redis receiver lacks a general server-error total and ignores the scrape
context inside INFO. Its finite pinned driver socket/retry bounds are documented;
**the YAML 2s timeout is not a promised Redis command deadline**. Application command
errors and server connection rejections have distinct, narrower definitions.
PostgreSQL locks include requested/held locks and have no granted-state dimension.
No unavailable measurement is invented or silently zero-filled.

Resource samples are a short synthetic smoke cost under unchanged hard limits,
not the later M9 controlled latency/overhead baseline. There is no hosted/AMD64
runtime claim, remote CI, new dashboard/alert threshold, external notification,
full M9 acceptance, business financial-reporting claim or developer DB migration.

Repository guidance discrepancy: AGENTS.md's infrastructure paragraph still calls
Redis infrastructure-only and caching future work. Current catalog/authentication/
worker code and its tests already use Redis. This slice instruments those existing
contracts as explicitly requested; it does not introduce a new cache, limiter or
worker architecture, and instruction files were preserved.

## Executed shared checks

All commands ran from the repository root with Python 3.12.16 on local ARM64 Docker.
Dependencies were installed once with
`backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-dev.txt`.
No lock resolution or dependency upgrade occurred. Subsequent gates used
`--no-install` and are explicitly partial repository validation.

- `backend/.venv/bin/python scripts/validate.py --gate backend-unit --gate backend-static --no-install`:
  **505 unit tests passed**, Ruff lint/format and mypy **169 app sources** passed;
  static checks also include both new acceptance scripts.
- `backend/.venv/bin/python scripts/validate.py --gate backend-integration --no-install`:
  **357 passed, 1 skipped** in 352.12 seconds, including real-process pool tests,
  deferred commit failure, aborted transaction deduplication, SQL cancellation,
  and existing cache/auth/order/inventory/audit/outbox/worker regressions. The
  existing skipped test requires explicit monitoring-stack acceptance (#59).
- `backend/.venv/bin/python scripts/validate.py --gate baseline --gate image --no-install`:
  Compose/dependency/secret checks and both nonroot production-image build/runtime
  gates passed. Startup did not migrate the disposable database; no developer
  database was selected. The frontend gate uses the unchanged standalone source.
- `backend/.venv/bin/python scripts/check-monitoring-config.py`: base plus receiver
  Collector policies, Prometheus, Loki and Tempo validated with immutable native
  images in network-disabled, bounded parser containers; owned parser cleanup passed.
- Additional fresh disposable PostgreSQL/Redis run of existing worker entrypoint,
  crash-after-claim recovery and Redis outage/recovery tests with
  `MONITORING_ENABLED=true`, `MONITORING_ENDPOINT=http://localhost:1`:
  **3 passed** in 6.57 seconds. Worker relay durability/graceful shutdown and
  retry-attempt preservation held with the Collector absent. The runner used the
  same `services`/guarded `disposable_database` owners and migrated only its new DB.

Frontend static/component/browser gates, separate migration gate, the full #58
runtime/retention matrix, #59/#60 complete stored-signal suites, remote CI and
full M9 baseline/incident/dashboard acceptance were not rerun for this backend/
receiver slice. Existing HTTP exporter interruption/privacy tests ran in the
backend suites. No result above claims all ten gates or milestone completion.

## Stored acceptance and resource evidence

`backend/.venv/bin/python scripts/check-infrastructure-observability.py` completed
with **exit 0**, including ownership-checked monitoring/service/database teardown.
It verified required restricted reads and denied operations, actual stored
PostgreSQL/Redis metrics, API/worker SQL and pool gauges/timeouts, Redis outcomes,
source/query/key canary exclusion, frozen target staleness/recovery and
Collector-absent API/worker work plus re-export after restart. The harness
rediscovers the ephemeral Collector host port after restart; it never changes
application endpoint/retry semantics. Explicit test-only metric force-flush errors
are expected during the absent-destination phase; business code never flushes.

The final native parser check includes both receiver configurations. Eight rounded
Docker resource samples over 36.86 seconds of the declared sequential SQL/Redis/
pool-timeout workload showed **598,967,583 bytes** peak aggregate displayed memory
under the unchanged **2,000,000,000-byte** budget. Collector sampled peak was
**69,352,817 bytes**, **2.51% CPU** (one logical CPU = 100%). Per-service sampled
peaks and the complete sanitized samples are in
[evidence/issue61/runtime.json](evidence/issue61/runtime.json).
All five monitoring containers were running without OOM or automatic restart
before intentional faults. These are smoke resource samples, with observer-command
cost, rounded Docker readings and no continuous-max/long-term capacity promise.

A final focused fresh-process pool rerun passed **2 tests in 7.59 seconds** after
keeping transaction-failure state through the pre-driver commit event. This avoids
counting a failed statement and later failed commit of the same transaction twice;
rollback or the next begin clears the sentinel. Final fast validation remains
**505 unit tests**, Ruff/format and mypy. Full integration remains **357 passed,
1 existing skipped**; the final focused rerun covers the subsequent small hook
correction. No unresolved schema/API migration or dependency work remains.

The issue's local six-criterion mapping is supported within the explicitly stated
pinned-version measurement boundaries. A custom enforceable Redis scrape deadline,
general Redis server-error counter, true SQLAlchemy queue waiter count, controlled
M9 speed/overhead baseline and hosted/runtime/CI claims are not manufactured from
unavailable APIs. No issue checkbox, status, commit or publication was changed.

The final evidence JSON initially triggered the baseline hex-entropy scanner on
its public Git revision, rather than a credential. That revision is retained in
the explicitly annotated Markdown line above; no scanner policy or secret baseline
was broadened. The gate was rerun after correcting the evidence representation.
