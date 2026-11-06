# PostgreSQL and Redis diagnostics — issue #61

This optional extension uses the existing Collector and SDK; there is no new
service, business endpoint, schema migration, or Grafana SQL data source.
`MONITORING_ENABLED=false` remains the application default. API and standalone
worker lifecycles share the established bounded, asynchronous export implementation
but own independent providers, with `restaurantos-api` / `restaurantos-worker`
resources and bounded `role=api|worker` metric attributes. No synchronous network
export runs in business request/transaction paths. Recording failures are ignored.

Issue #62 adds `MONITORING_WORKER_SLOT` (**0–31**) for worker process metrics.
Assign distinct slots to concurrent workers targeting the same Collector, and
stop a slot's prior process before reusing it. All worker SQL/Redis/pool metrics
carry bounded `worker_slot`; API dimensions are unchanged. Without an assigned
slot, worker process metrics are suppressed with a safe startup warning, while
worker traces and durable event gauges remain available. This prevents healthy
worker counters from overwriting one another. See the [slot contract](../docs/api/events.md#worker-metric-producer-slots)
for reset/rate and durable-gauge rules. Slot assignments are operator configuration;
duplicate assignments are invalid and are not automatically detected.

## Versions and source review

The installed/locked Python versions are SQLAlchemy **2.0.52**, OTel SDK/API and
OTLP HTTP **1.45.1**, redis-py **8.1.0**, Python **3.12**. Server acceptance uses
PostgreSQL **16** and Redis **7** from the existing disposable service definitions.
No dependency pins changed. The Collector image remains **0.164.0**, digest in
`images.lock.json`; its Contrib modules are **0.164.1**, source
[`9d85835b`](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/9d85835bdee87a7e33e315da1a875cbaabd50b91).
The receiver READMEs, metadata, client/scraper/config/factory implementations at
that revision were reviewed, including go-redis **v9.23.0** defaults. Current `main`
documentation is not the contract. Sources:

- [Pinned PostgreSQL receiver](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/9d85835bdee87a7e33e315da1a875cbaabd50b91/receiver/postgresqlreceiver)
- [Pinned Redis receiver](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/9d85835bdee87a7e33e315da1a875cbaabd50b91/receiver/redisreceiver)
- [SQLAlchemy 2 engine events](https://docs.sqlalchemy.org/en/20/core/events.html)
- [PostgreSQL 16 statistics and visibility](https://www.postgresql.org/docs/16/monitoring-stats.html)
- [Redis ACL rules](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/)
- [go-redis v9.23.0 socket/retry defaults](https://github.com/redis/go-redis/blob/v9.23.0/options.go)

## Application metrics

Every name below has the prefix `restaurantos.`. Histograms use seconds and the
existing explicit boundaries .005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 30.
Counters use unit `1`; connection gauges/acquiring use `{connection}`. Prometheus replaces dots with
underscores, adds `_seconds` for duration histograms (with `_bucket`, `_sum`,
`_count`), and `_total` for monotonic counters. Examples:
`restaurantos_sql_duration_seconds_count`, `restaurantos_pool_used`,
`restaurantos_redis_operations_total`, `restaurantos_catalog_cache_lookups_total`.

| Metric | Instrument | Additional bounded attributes / meaning |
|---|---|---|
| `sql.duration` | histogram, s | `operation`, `outcome`; cursor execution including error/cancellation; excludes pool wait and result iteration/ORM decoding |
| `sql.slow` | counter | Same; elapsed >= `MONITORING_SQL_SLOW_SECONDS`, default **0.5 seconds**, validated **0.001–60 seconds** |
| `sql.failures` | counter | Same; one per failed timed cursor execution |
| `transaction.failures` | counter | `outcome`; first database execution/commit error while a transaction is active; reset at next transaction boundary |
| `pool.capacity` | observable gauge | Base configured pool size; lazy unopened slots are included |
| `pool.limit` | observable gauge | Configured size + allowed overflow; not PostgreSQL's server max_connections |
| `pool.used` | observable gauge | Actual checked-out connections |
| `pool.idle` | observable gauge | Actual opened, checked-in connections; not unused potential slots |
| `pool.overflow` | observable gauge | Open overflow connections; SQLAlchemy's negative lazy-initialization bookkeeping is normalized to zero |
| `pool.acquiring` | up/down counter | Acquisitions in progress, including connection establishment and worker pre-ping |
| `pool.acquire.duration` | histogram, s | `outcome`; public `Pool.connect()` boundary including queue wait/connect/pre-ping |
| `pool.acquire.failures` | counter | `outcome=timeout|connection|cancelled` |
| `redis.duration` | histogram, s | `operation`, `outcome`; existing total command budget includes acquire/connect/reply |
| `redis.operations` | counter | Same; command attempts, with success and classified failures |
| `catalog.cache.lookups` | counter | `cache=menus|menu_items`, `outcome=hit|miss|bypass` |

SQL categories come only from SQLAlchemy compiled statement flags:
`SELECT|INSERT|UPDATE|DELETE|OTHER`. Text/driver statements are `OTHER`, without
parsing SQL. Outcomes are `success`, `cancelled`, `deadlock` (40P01),
`serialization` (40001), `lock` (55P03), `transaction` (other class 40), `constraint`
(class 23), `connection` (class 08), `interrupted` (class 57), or `database`.
Ordinary session cleanup/read rollback, explicit cancellation/validation of a
business command without a database error, and ordinary transaction rollback do
**not** increment failed-transaction counts. This metric counts observed failed
DB transactions, including failed reads, rather than all rejected business commands.
An execution failure and its transaction failure are separate denominators.

SQLAlchemy has **no supported public waiter-count API**. `pool.acquiring` is
explicitly not a queue waiter gauge. Pool size/timeout limits and transaction
ownership are unchanged. The HTTP test adapter's NullPool emits SQL metrics but
**no capacity/idle/used/overflow gauges**; a missing pool gauge is not zero.
The process tests construct the real API and worker factories in fresh processes
and synchronize inside actual overlapping acquisition calls.

Redis operation categories are the adapter command allowlist in
`core/diagnostics.py`; unknown commands become `OTHER`. No key, argument or
payload is inspected. Outcomes are `success|timeout|connection|command|closed|
cancelled|internal`. Unexpected non-driver exceptions retain their original
behavior and use `internal`. Worker ranged XPENDING parsing retains its existing
parser/deadline. Close/cleanup is not counted as a Redis application command.
API transport totals combine cache and authentication command attempts; worker
transport totals describe stream operations. They are not feature hit ratios.

Cache observations remain in catalog's authorized read service. A hit is a valid
usable response, including an empty list; item hits also pass live inventory
validation. An attempted lookup without a usable result is a miss (including a
Redis error); a skipped lookup, disabled/unwired cache or open circuit is a bypass.
Only one observation is emitted per completed logical lookup decision. Foreign or
unauthorized requests are rejected before any lookup observation. Cancellation
before a decision emits none. Payload source-age, absolute ten-second age, targeted
invalidation, five-second circuit cooldown, DB fallback, live availability and
independent auth fallback are unchanged. Redis server keyspace hits/misses have
a different denominator and must never substitute for this ratio.

Counters/histograms are process-local best effort, reset on restart and may lose
observations during export failure/crash. Pool gauges read the current engine's
public pool methods without queries, queue introspection or connection acquisition.
Engine listeners attach once; execution timing lives on the execution context,
with success/error/cancellation cleanup. No SQL/Redis auto-instrumentation is enabled.

## Restricted identities and opt-in setup

Provision identities explicitly; application startup and validation never provision
them on the developer database. For PostgreSQL, review and run
`monitoring/postgres-monitor.sql` as a role/database administrator against the one
intended database using `psql -d <database> -f monitoring/postgres-monitor.sql`.
Use local private connection configuration rather than a password-bearing command
line. The script deliberately fails if the dedicated role already exists: inspect
its memberships and grants before deciding how to reconcile it. Set its password
with psql's `\password restaurantos_monitor`, then store the same value in
`.local-monitoring/postgres_monitor_password`. Never put secrets in SQL history,
command arguments, source control or diagnostics.

The dedicated role has LOGIN, CONNECT to the one target, connection limit **2**,
no elevated role memberships, no superuser/create-role/create-DB/replication/BYPASSRLS,
and SELECT only on five statistics/catalog views. PostgreSQL 16 normally grants
these view reads to PUBLIC already; explicit grants support hardened installations.
The receiver's selected count/statistics queries need neither **pg_monitor** nor
**pg_read_all_stats**. Backend counts use database names visible without exposing
other sessions' SQL text; activity-state/query-sample collection is not enabled.
Default transaction read-only plus statement **1500 ms**, lock **500 ms**, and
idle-in-transaction **2 s** limits add safeguards; table ACLs remain the actual
boundary even if the login turns read-only off. No business-schema grants are made.
Inherited PUBLIC catalogue/CONNECT/TEMP privileges still apply; this is a statistics
reader, not a promise to conceal all cluster metadata. Inspect/revoke inappropriate
PUBLIC business grants as a separate authorized security change, not implicitly
through this setup script. Acceptance denies business SELECT/INSERT, privileged
file reads, role creation and signaling another role's backend.

On Redis 7 create a distinct ACL user with the following **rules**, using a private
admin connection/input file (supply a generated secret without putting it in process
arguments or logs): `reset on >PASSWORD -@all +hello +info resetkeys resetchannels`.
Store its password in `.local-monitoring/redis_monitor_password`. Only HELLO
(handshake/authentication) and INFO are granted. No key access, command execution,
CONFIG, ACL, MONITOR, Pub/Sub or stream access is permitted. Client SETINFO attempts
by the receiver's driver are nonfatal and require no ACL grant. The application's
Redis identities and pools are unchanged. INFO ALL includes aggregate command
statistics but no keys, command arguments or payloads; this configuration exports
only the selected aggregate metrics below, with command-level metrics disabled.

For a **new** local monitoring state:

```sh
backend/.venv/bin/python scripts/local-monitoring.py init --diagnostics
# Provision the two identities and private password files as described above.
export MONITORING_POSTGRES_ENDPOINT=host.docker.internal:5433
export MONITORING_POSTGRES_DATABASE=restaurantos
export MONITORING_REDIS_ENDPOINT=host.docker.internal:6379
backend/.venv/bin/python scripts/local-monitoring.py config
backend/.venv/bin/python scripts/local-monitoring.py up
```

Retain the private directory's restrictive permissions; mounted secret files must
be readable by the nonroot Collector (0444 inside a host-only 0700 directory,
as with existing Grafana files). For existing initialized state, explicitly set
`"diagnostics": true` in its ignored state.json after provisioning; `init` never
overwrites credentials. Keep the three nonsecret endpoint/database variables set
for `up/config/down`. `down` retains the developer monitoring volumes. Do not use
`down --volumes` on developer resources. To disable collection set the state flag
false and run `up`; the optional second Collector config and secrets are omitted.

The host overlay supplies Collector connectivity through Docker Desktop. For
container mode attach only the Collector to the chosen private application network
and use internal PostgreSQL/Redis DNS/ports. Do not publish database/Redis ports
for collection or give Grafana these identities. The test runner attaches only
its owned Collector to its owned PostgreSQL/Redis network. Cleartext receiver TLS
is deliberately limited to these local private paths; a remote deployment requires
separately reviewed TLS/network configuration and is outside this issue.

## Receiver measurements, cadence and limitations

Both receivers collect every **10 seconds**, leaving headroom inside the existing
30-second exporter expiration for ordinary collection and batching delay. PostgreSQL's **2-second collection
context** bounds all queries together, backed by the login's server statement
limits. Only one database is explicitly selected for both discovery and statistics;
no automatic multi-database enumeration. Its receiver pool is capped at **one open,
one idle connection**, with **60-second** maximum idle time. This is independent of
application pool configuration. Table, index, function, replication, WAL filesystem,
vector, query samples, query plans and top-query collection are explicitly disabled.
No extensions are installed and no full business-table/history scans occur.

**Pinned Redis limitation:** the receiver accepts scraper `timeout: 2s` but its
Scrape/INFO implementation uses `context.Background()`, so this is **not an enforced
2-second command deadline**. go-redis v9.23.0 supplies finite defaults: 5-second
dial/read/write timeouts, five dial attempts, three command retries, bounded retry
backoff and a 6-second pool timeout. A cold failed dial can take longer than one
interval. These options are not exposed by this receiver, and no dependency was
upgraded to pretend otherwise. There is one serial INFO collector; the hard
Collector memory/shutdown limits still apply. Pause/unpause acceptance measures
failure, series expiration and recovery on the actual pinned binary. A stricter
operator-selected Redis scrape deadline requires a separately reviewed upstream
receiver fix; do not infer it from the YAML timeout. No business Redis budgets,
limits, retries or cancellation behavior were changed.

The pinned receiver lacks a general Redis server error counter and does not
export `errorstats`/failed-call totals. `redis.connections.rejected` exposes server
connection rejections; application `redis.operations{outcome="command"}` exposes
server command failures seen by the API/worker. Neither claims to count every
server error. PostgreSQL lock counts include held and requested locks and the
receiver's own locks; this version has no granted/waiting-state dimension. Use
SQL timing plus counts/deadlocks to investigate pressure; do not label these
counts as waiting requests or exact blocking duration.

PostgreSQL lock counts aggregate away relation names before export. Bounded
`mode`, `lock_type`, and `collection_scope=database|server` distinguish shared and
database locks without duplicate series. Redis CPU time retains its bounded
`state`; other receiver datapoints have no attributes. Resource/endpoint/database/
relation names, scope attributes/schema URLs and descriptions are removed;
resources become only `restaurantos-postgresql` or `restaurantos-redis`.
The application pipeline independently allowlists metric names and bounded labels,
removes descriptions/schema metadata and enforces units. Existing HTTP/synthetic/
frontend/log/trace privacy pipelines remain separate.

Exact enabled OTLP metrics and units (all others explicitly disabled):

| Receiver metric | Type | Unit |
|---|---|---|
| `postgresql.backends` | nonmonotonic cumulative sum | `1` |
| `postgresql.blks_hit` | counter | `{blks_hit}` |
| `postgresql.blks_read` | counter | `{blks_read}` |
| `postgresql.commits` | counter | `1` |
| `postgresql.connection.max` | gauge | `{connections}` |
| `postgresql.database.locks` | gauge | `{lock}` |
| `postgresql.deadlocks` | counter | `{deadlock}` |
| `postgresql.rollbacks` | counter | `1` |
| `postgresql.temp.io` | counter | `By` |
| `postgresql.temp_files` | counter | `{temp_file}` |
| `redis.clients.blocked` | nonmonotonic cumulative sum | `{client}` |
| `redis.clients.connected` | nonmonotonic cumulative sum | `{client}` |
| `redis.commands` | gauge | `{ops}/s` |
| `redis.commands.processed` | counter | `{command}` |
| `redis.connections.received` | counter | `{connection}` |
| `redis.connections.rejected` | counter | `{connection}` |
| `redis.cpu.time` | counter | `s` |
| `redis.keys.evicted` | counter | `{key}` |
| `redis.keys.expired` | counter | `{event}` |
| `redis.keyspace.hits` | counter | `{hit}` |
| `redis.keyspace.misses` | counter | `{miss}` |
| `redis.maxmemory` | gauge | `By` |
| `redis.memory.fragmentation_ratio` | gauge | `1` |
| `redis.memory.peak` | gauge | `By` |
| `redis.memory.rss` | gauge | `By` |
| `redis.memory.used` | gauge | `By` |
| `redis.net.input` | counter | `By` |
| `redis.net.output` | counter | `By` |
| `redis.uptime` | counter | `s` |

Prometheus names follow the same dot-to-underscore/unit/counter mapping. In
particular `postgresql_backends`, `postgresql_connection_max`,
`postgresql_database_locks`, `postgresql_commits_total`,
`postgresql_rollbacks_total`, `postgresql_deadlocks_total`,
`postgresql_temp_io_bytes_total`, `redis_memory_used_bytes`,
`redis_keys_evicted_total`, `redis_connections_rejected_total`,
`redis_commands_per_second` and `redis_uptime_seconds_total` are the exported names.
Redis maxmemory **0** truthfully means unlimited, not missing data.

The Prometheus exporter retains last-received samples for at most **30 seconds**;
a failed receiver eventually removes its series rather than exporting zero.
Prometheus observes the missing series at its next five-second scrape. Correlate
with `up{job="collector-self"}`, `up{job="collector-telemetry"}` and Collector
`otelcol_scraper_errored_metric_points` / `otelcol_scraper_scraped_metric_points`
plus rotated Collector stderr. The pinned Redis scraper can report zero errored
*points* on a complete failed INFO read: that counter alone is not a health check.
Require presence/freshness of expected Redis series; no fresh zero means healthy.
A healthy Collector health endpoint proves process liveness, not DB/Redis health.
No dashboards or alert thresholds are selected here (#64–#66).

The five-service **2 GB** memory allocation, exporter queues, request-body bounds,
retry budgets, retention and nonroot/security settings are unchanged. Resource
samples and verification boundaries are in the [dated issue review](../docs/milestone9-observability/verification-milestone9-issue61.md).
