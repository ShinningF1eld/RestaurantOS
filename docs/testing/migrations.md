# Migration verification

`scripts/verify-migrations.py` exercises two independent PostgreSQL upgrade paths.
The clean path upgrades an empty database to the repository's unique current
Alembic head and runs `alembic check` for model drift. The legacy path starts at
`c48b7e02f315`, seeds tenant-owned restaurant data, historical order snapshots,
and an inventory opening movement, then verifies that those rows survive the
upgrade. It also asserts that the newly introduced inventory flags leave legacy
menu items untracked and legacy orders unprocessed.

The selected legacy baseline is after tenancy ownership, order item snapshots,
and the inventory ledger were introduced, and immediately before recipe tracking
and order inventory processing. That makes the fixture representative of data
those later migrations must preserve. The final order-inventory migration has a
prohibited downgrade guard: the harness adds a processed order, consumption
movement, and idempotency submission, attempts the downgrade, and confirms that
the revision, public schema, stock history, and submission history remain intact.

## Safe disposable database lifecycle

The harness requires an explicit `TEST_DATABASE_URL`; it never reads
`DATABASE_URL` as a fallback and does not load `.env` files. The configured URL
must target PostgreSQL, name a database ending in `_test`, and use an allowed
test host: `localhost`, `127.0.0.1`, `::1`, or the GitHub Actions service name
`postgres`. A local Compose port can be published on loopback; jobs running in
the Compose network can use `postgres:5432`.

The configured database is only a connection template. Each run creates a new
database with a random suffix, performs all Alembic operations against that
database, and drops only that generated name in a `finally` block, including
when the migration command or assertions fail. The role needs permission to
create and drop databases. The template database itself is never migrated or
dropped.

Other runners can use the same guarded API from `scripts/test_support`:

```python
from test_support.disposable_postgres import disposable_database

with disposable_database(prefix="restaurantos_browser") as database:
    environment = database.environment()
    # database.async_url, database.sync_url, and environment target one unique DB.
```

`read_test_url(environ=...)` supports validation against an explicit environment
mapping. Callers with a dedicated test-service hostname can pass an explicit
`allowed_hosts` set; callers should not derive that set from untrusted input.

## Commands

In PowerShell, set a disposable-database template that ends in `_test`, then run
the verifier with the backend virtual environment:

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5433/restaurantos_test"
& .\backend\.venv\Scripts\python.exe .\scripts\verify-migrations.py --help
& .\backend\.venv\Scripts\python.exe .\scripts\verify-migrations.py
```

The default runs clean and legacy scenarios. Use `--scenario clean` or
`--scenario legacy` to run one path. A cleanup check can be exercised with an
intentional failure after a database has been created or upgraded:

```powershell
& .\backend\.venv\Scripts\python.exe .\scripts\verify-migrations.py `
  --scenario clean --inject-failure-after clean-upgrade
```

That command must return nonzero and print the allocated database name. The
context manager drops that name while unwinding the injected exception. The
clean and seeded scenarios themselves also fail if an upgrade, model check,
data-preservation assertion, downgrade guard, or cleanup step fails.

## Maintaining the representative baseline

The verifier resolves the current Alembic head from the migration graph at run
time and requires a single head. Keep `c48b7e02f315` as the previous-revision
fixture while it remains an ancestor of that head and continues to exercise the
newest relevant migrations. When the schema or supported legacy state changes,
review the migration chain and update `LEGACY_BASELINE`, the seed rows, and the
preservation assertions together. Prefer a baseline immediately before the
migrations whose compatibility matters; do not advance it just because the
repository head changed. If the order inventory guard is removed or replaced,
update the downgrade scenario to cover the policy that supersedes it.
