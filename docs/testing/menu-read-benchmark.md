# Milestone 7 menu-read benchmark

`scripts/benchmark-menu-reads.py` measures the real authenticated HTTP request
path for the two Milestone 7 catalog reads. It uses the current uncached
PostgreSQL implementation; it does not implement or configure Redis.

## Reproduce

Requirements: the supported Python environment with the locked backend dev
dependencies installed, and a reachable PostgreSQL server whose role can create
and drop databases. Set only the connection template in `TEST_DATABASE_URL`;
the value must use an allowed local/test-service host and name a PostgreSQL
database ending in `_test`. The repository's test Compose service uses temporary
storage and a random loopback port.

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5433/restaurantos_test" # pragma: allowlist secret
& .\backend\.venv-m6-dev\Scripts\python.exe .\scripts\benchmark-menu-reads.py
```

The script reads no `.env` file and does not use `DATABASE_URL` as a fallback.
`scripts/test_support/disposable_postgres.py` validates the template, allocates
a random `restaurantos_benchmark_*_test` database, and drops only that generated
database in a `finally` block. Alembic, deterministic seed operations, the API,
and all benchmark requests target the allocated database. The supplied template
database is never migrated, truncated, seeded, or dropped. Use
`--inject-failure-after seed` or `--inject-failure-after measurement` to exercise
nonzero failure and cleanup paths; these test-only switches are hidden from the
normal help output.

For a short harness smoke run, reduce the workload explicitly:

```powershell
& .\backend\.venv\Scripts\python.exe .\scripts\benchmark-menu-reads.py `
  --requests 20 --warmup 2 --repetitions 1 --concurrency 1,2
```

Defaults are 1,000 measured requests, 50 excluded warm-up requests, three
repetitions, concurrency levels 1/10/25/50, and all four scenarios. These
settings are configurable with `--requests`, `--warmup`, `--repetitions`,
`--concurrency`, and `--scenarios` (comma-separated scenario names).

## Deterministic workload

Each fresh database contains one organization, one restaurant, one Owner
membership, one Manager membership assigned to the restaurant, four menus, and
40 items per menu (160 total). The authenticated benchmark principal is the
assigned Manager, so reads include branch-scoped authorization. Four inventory
ingredients each start with 5,000.000 g. Ten items in each menu (40 total, 25%)
have one 25.000 g recipe component and inventory tracking enabled; the other
items are untracked. Names, descriptions, prices, amounts, and item/menu ordering
are fixed. Database IDs and login credentials are generated only inside the
disposable run. The workload state is newly seeded on every run.

| Scenario | Request mix |
|---|---|
| `menu-list` | 100% `GET /restaurants/{restaurant_id}/menus` |
| `menu-items` | 100% `GET /menus/{menu_id}/items`, round-robin across four menus |
| `mixed-read` | 20% menu-list and 80% menu-item list |
| `mixed-write` | 80% menu-item list, 10% item update, and 10% menu update |

The mixed-write sequence is fixed and can be run after caching is introduced to
compare read behavior while catalog edits occur. Responses are validated and
successful non-2xx statuses count as errors. All measured calls use the normal
login cookies, auth middleware, current tenancy checks, catalog service and
response serialization. Warm-ups use the same endpoint mix and are excluded from
latency and query totals. Repetitions restart each scenario's deterministic
request index.

The isolated API uses the normal development connection pool settings for its
single long-lived server loop. The disposable database is still selected
explicitly through the generated `DATABASE_URL`; test mode's `NullPool` is not
used because it exists to isolate TestClient's independent event loops.

## Metrics and artifacts

Latency is client-observed HTTP duration. P50/P95/P99 use nearest-rank percentiles.
PostgreSQL queries are counted with SQLAlchemy's `before_cursor_execute` event
inside per-request ASGI context. The response-local query counter includes SQL
executed for auth, tenancy, catalog and live availability in that request;
migration, seed, login, server health and warm-up SQL are excluded from measured
totals. The report records total SQL statements and average queries per measured
request. For this baseline, `cache_hit_ratio` is null and its label explicitly
says `N/A`.

The console prints one line per scenario/concurrency/repetition. A successful run
atomically writes a versioned JSON result under `artifacts/benchmarks/`; generated
results are git-ignored. Each result includes the source commit, script version,
configuration, Python/library/PostgreSQL versions, host/CPU/memory where
available, dataset, request mixes, measurement method, timestamps, and per-run
metrics. Runtime credentials and raw authentication identifiers are not included.
The `schema_version`, `cache_mode`, `cache_state`, and nullable cache-hit field
are intended to hold later cached results in the same shape. Cold/warm cache
states are not applicable before Redis caching exists. For the later comparison,
record a cache-cleared cold fill separately from warm hits, while retaining the
same request mix and run configuration; keep the exact command and JSON artifact
and match dataset, scenario, concurrency, repetitions and request counts.

## Dashboard caching evidence

Use the baseline and post-cache artifacts to decide whether dashboard caching is
worth a separate design. At minimum, compare dashboard endpoint P50/P95/P99 and
query count at the same concurrency with and without cache, including the source
query shape, authorization cost, data freshness requirements, and behavior after
underlying order/inventory changes. This benchmark intentionally does not call the
dashboard endpoint, so it does not claim evidence for or against dashboard cache
implementation.
