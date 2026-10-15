# Milestone 8 maintenance initialization and analytics rebuild

Issue #38 implements offline, per-restaurant maintenance. These commands are
explicit application operations, **not validation commands**. Do not run them on
the application database merely to verify a change. The migration gate rehearses
this procedure on seeded disposable databases, including custom-format backup,
restore, CLI initialization/rerun/rebuild/reconciliation and downgrade rejection.

## Preconditions and trust

Use the reviewed release, trusted backend environment and PostgreSQL credentials.
The CLI authenticates provenance using PostgreSQL `session_user`; organization
and restaurant flags select scope but do not grant HTTP permissions. There is no
fabricated Owner principal. Restrict these credentials to trusted operators.
`--maintenance-confirmed` is an operator attestation; it does not stop processes
or establish an online maintenance mode.

1. Announce the maintenance window. Stop business request admission, stop API
   processes and stop **all** workers with Ctrl+C/SIGTERM. Wait for their exit and
   in-flight transactions to finish. Stop other scripts using business writes.
   Keep PostgreSQL running. Retain the developer `postgres_data` volume.
2. Inspect actual revision, take a backup and verify restoration before migration.
3. Explicitly migrate, initialize every intended organization/restaurant pair,
   reconcile, and inspect retained counts.
4. Start workers, then restart API/request admission and resume business writes.
   Inspect backlog recovery and reconcile again after queued work settles.

For local developer Compose, from the repository root in PowerShell:

```powershell
$ErrorActionPreference = 'Stop'
$m8Python = (Resolve-Path backend/.venv/Scripts/python.exe).Path
$m8Container = 'restaurantos-postgres'
$m8Database = 'restaurantos'
$m8Restaurant = 1 # Choose the verified restaurant; repeat for every intended branch.
docker exec $m8Container psql -U restaurantos -d $m8Database -c 'SELECT version_num FROM alembic_version;'
if ($LASTEXITCODE) { throw 'Revision inspection failed' }
docker exec $m8Container psql -U restaurantos -d $m8Database -c 'SELECT id,organization_id,name FROM restaurants ORDER BY id;'
if ($LASTEXITCODE) { throw 'Scope inspection failed' }
docker exec $m8Container psql -U restaurantos -d $m8Database -c "SELECT pid,state,xact_start FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();"
if ($LASTEXITCODE) { throw 'Session inspection failed' }
# Investigate remaining application sessions before proceeding.
$m8Organization = (docker exec $m8Container psql -U restaurantos -d $m8Database -tAc "SELECT organization_id FROM restaurants WHERE id=$m8Restaurant").Trim()
if ($LASTEXITCODE -or -not $m8Organization) { throw 'Unknown scope' }
$m8Stamp = Get-Date -Format yyyyMMdd-HHmmss
$m8Dump = "/tmp/restaurantos-before-m8-$m8Stamp.dump"
New-Item -ItemType Directory -Force .local-backups | Out-Null
$m8LocalDump = Join-Path (Get-Location) ".local-backups/restaurantos-before-m8-$m8Stamp.dump"
docker exec $m8Container pg_dump -U restaurantos -d $m8Database -Fc -f $m8Dump
if ($LASTEXITCODE) { throw 'Backup failed' }
docker cp "${m8Container}:$m8Dump" $m8LocalDump
if ($LASTEXITCODE) { throw 'Backup copy failed' }
docker exec $m8Container pg_restore --list $m8Dump
if ($LASTEXITCODE) { throw 'Invalid archive' }
$m8Restore = 'restaurantos_m8_restore_' + [guid]::NewGuid().ToString('N') + '_test'
docker exec $m8Container createdb -U restaurantos $m8Restore
if ($LASTEXITCODE) { throw 'Restore database creation failed' }
docker exec $m8Container pg_restore --exit-on-error -U restaurantos -d $m8Restore $m8Dump
if ($LASTEXITCODE) { throw 'Restore verification failed; retain database for investigation' }
$m8Check = 'SELECT version_num FROM alembic_version; SELECT count(*),sum(total) FROM orders; SELECT count(*),sum(quantity) FROM inventory_balances;'
docker exec $m8Container psql -U restaurantos -d $m8Database -c $m8Check
if ($LASTEXITCODE) { throw 'Source data inspection failed' }
docker exec $m8Container psql -U restaurantos -d $m8Restore -c $m8Check
if ($LASTEXITCODE) { throw 'Restored data inspection failed' }
# Compare both results and critical historical snapshots before proceeding.
```

Do not assume an old documented revision is the current application revision.
The expected release head for this slice is `c3d8e1f52a74`, after T7's
`b2c7d9a41e63`. Review any unexpected starting revision before continuing.
Retain the backup and restore database until cutover is verified. A shared or
hosted PostgreSQL installation needs its own approved credential/backup process;
the commands above describe the existing local Compose installation.

## Explicit migration and initialization

Continue in the same PowerShell session. Verify that the backend's `DATABASE_URL`
selects the inspected application database. Alembic uses **DATABASE_URL**, not
`TEST_DATABASE_URL`; setting only a test variable does not change its target.
Do not print credential-bearing URLs. Commands below assume the stopped backend's
reviewed `.env` configuration. Migration is a separate deliberate step; the CLI
and worker never invoke Alembic.

```powershell
Push-Location backend
try {
    & $m8Python -m alembic current
    if ($LASTEXITCODE) { throw 'Revision inspection failed' }
    & $m8Python -m alembic upgrade head
    if ($LASTEXITCODE) { throw 'Migration failed; keep writers and workers stopped' }
    & $m8Python -m alembic check
    if ($LASTEXITCODE) { throw 'Model drift detected' }
    & $m8Python -m app.modules.events.cli initialize --organization-id $m8Organization --restaurant-id $m8Restaurant --maintenance-confirmed --reason 'Approved M8 baseline cutover'
    if ($LASTEXITCODE) { throw 'Initialization failed; keep maintenance window open' }
    & $m8Python -m app.modules.events.cli analytics-reconcile --organization-id $m8Organization --restaurant-id $m8Restaurant
    if ($LASTEXITCODE) { throw 'Reconciliation command failed' }
    # Require matches:true; discrepancies require investigation before restart.
    & $m8Python -m app.modules.events.cli status
    if ($LASTEXITCODE) { throw 'Status command failed' }
} finally { Pop-Location }
```

On Unix use `.venv/bin/python` and the same module, command names and flags.
`--help` requires no secrets or running database. Each scope commits independently;
repeat with the verified UUID and restaurant ID for other branches.

Initialization seeds all current order revision watermarks, completed totals by
UTC creation date and retained deletion tombstones. It emits no historical order
or inventory events. A currently active low ingredient without a producer episode
gets a suppressed `maintenance_initialization` episode: display it as **low at
initialization**, using database observation time and immutable current
name/unit/quantity/threshold snapshots. Existing producer episodes and their true
history are preserved; they are not relabelled as baselines. It rebuilds alert
history/current state from producer facts and persists initialization provenance
in the same transaction. Baseline suppression is a durable producer fact, even
though no notification event/stub is manufactured for the baseline.

Successful JSON contains scope, operation UUID, kind, outcome, observation time,
authenticated database role, `reason_recorded` and scoped `retained_counts` for
events, deliveries, receipts, attempts, replays, maintenance operations, projected
episodes/current states, notification stubs and diagnostics. It does not print
reason text, payloads, credentials or raw database exceptions. Use safe reasons
without secrets/customer data. Trusted database inspection can retrieve recorded
reasons from `event_maintenance_operations` by operation UUID.

## Interruption, rerun and analytics reconstruction

An interrupted transaction rolls back analytics, baselines, alerts and marker
together. With workers/writes still stopped, rerun the identical command/scope.
If commit succeeded but the response was lost, the committed initialization marker
returns `already_initialized` with its original operation UUID/time. Rerun does
not refresh projections or create episodes, including after a baseline resolved.
Never delete the marker to force a rerun. Scopes completed before a multi-branch
interruption remain committed; rerun each intended scope safely.

Stock deductions or threshold changes that stay low keep the suppressed baseline.
Recovery/threshold reduction/archive resolves it; a subsequent genuine entry into
low stock creates a normal unsuppressed episode. Existing queued events and
receipts remain intact; revision watermarks prevent old completion/deletion work
from double counting or resurrecting removed contributions.

For later analytics corruption, repeat the stop/quiesce, revision inspection and
verified-backup procedure above. From `backend/`:

```powershell
& $m8Python -m app.modules.events.cli analytics-rebuild --organization-id $m8Organization --restaurant-id $m8Restaurant --maintenance-confirmed --reason 'Reconstruct completed sales after investigation'
if ($LASTEXITCODE) { throw 'Rebuild failed; keep maintenance window open' }
& $m8Python -m app.modules.events.cli analytics-reconcile --organization-id $m8Organization --restaurant-id $m8Restaurant
if ($LASTEXITCODE) { throw 'Reconciliation command failed' }
```

Require `matches:true` before restart. Rebuild requires an initialized scope,
reconstructs current contributions/totals and deletion watermarks, records a new
operation, and leaves alert history and all delivery/attempt/replay/receipt/stub/
diagnostic records untouched. It never deletes receipts to replay history.
Its transaction can also be rerun after interruption or an ambiguous response;
each committed rebuild has its own provenance UUID.

M8 retains all these records and does not trim Streams. `status` reports global
backlog, retained delivery history and Redis size; maintenance output reports
scoped retained counts. Monitor PostgreSQL disk and Redis memory growth. This is
an accepted M8 limitation, not a production retention policy. Downgrade refuses
to discard maintenance provenance. Keep workers/writes stopped after failures;
prefer investigating/repairing additive state. Restore only through a separate
explicit recovery decision with reconciliation of writes since backup. Never
remove the developer volume or run an automatic application downgrade.
