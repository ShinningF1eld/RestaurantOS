# Milestone 4 cutover and recovery

Local cutover and acceptance completed on **2026-10-02** after PostgreSQL recovered.
The live database is at `94d8f2c5b013`, restaurant 1 belongs to organization 1,
and the sole existing user has an active OWNER membership. The bootstrap ran
twice with one membership and one bootstrap audit entry.

Before migration, a custom-format backup was saved to the ignored local path
`.local-backups/restaurantos-before-m4-20261002-064956-utc.dump`. Restoration into
a disposable database matched the original revision and every existing user,
restaurant, menu, menu item, order and order item. After live migration, row
fingerprints confirmed all original data was unchanged except the new restaurant
organization association. No live downgrade or restore was performed.

## Back up before applying constraints

For subsequent cutovers, stop API writers while applying constraints.
From the repository root, create a timestamped backup in the ignored folder:

```powershell
$m4BackupStamp = Get-Date -Format yyyyMMdd-HHmmss
$m4ContainerBackup = "/tmp/restaurantos-before-m4-$m4BackupStamp.dump"
$m4LocalBackup = Join-Path (Get-Location) ".local-backups/restaurantos-before-m4-$m4BackupStamp.dump"
New-Item -ItemType Directory -Force -Path .local-backups | Out-Null
docker exec restaurantos-postgres pg_dump -Fc -U restaurantos -d restaurantos -f $m4ContainerBackup
if ($LASTEXITCODE -ne 0) { throw "Backup failed" }
docker cp "restaurantos-postgres:$m4ContainerBackup" $m4LocalBackup
if ($LASTEXITCODE -ne 0) { throw "Copy failed" }
docker exec restaurantos-postgres pg_restore --list $m4ContainerBackup
```

Verify restoration into a separately named, empty database before any shared
deployment. With a **new** disposable name, use `createdb -U restaurantos NAME`
and `pg_restore -U restaurantos -d NAME PATH_TO_CONTAINER_DUMP` inside the
container. Verify the Alembic revision and representative user, restaurant and
historical order rows in that restored database. Keep the backup until cutover
and acceptance are verified. Do not remove the Compose volume.

## Migration and the existing one-user workspace

`83c7e1b4a902` creates and backfills the development organization without granting
access. `94d8f2c5b013` checks for multiple memberships per user before DDL,
backfills any remaining null restaurant associations, numbers the development
organization 1, makes restaurant scope non-null and replaces user/org uniqueness
with **user uniqueness**. A duplicate membership aborts the upgrade instead of
choosing an organization silently. New organizations receive subsequent unique
numbers while foreign keys retain UUID storage IDs.

From `backend`, after backup:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic check
.venv/Scripts/python.exe -m app.modules.tenancy.cli bootstrap-existing
```

The explicit command requires exactly one user and one restaurant, an active
user, and development organization number 1. It refuses a user/restaurant already
associated with another organization. It creates or promotes only the sole
user's OWNER membership and logs that action atomically. Repeating it makes no
duplicate membership or audit entry. Owners have implicit access to every
restaurant in their organization, so this assigns ownership of the existing
restaurant. It never prints account passwords or tokens. The migration performs
the restaurant association; the command confirms it and assigns the owner.

Log in as the existing user and inspect `/api/access`, `/api/organization` and
`/api/restaurants`: OWNER, organization number 1 and the existing restaurant
must be present. Verify a historical order's snapshots. The local cutover
verified the persisted membership/organization/restaurant association and all
original row fingerprints; authenticated API behavior was exercised in isolated
test databases rather than logging in as the existing user.

For a fresh workspace without an existing restaurant, provision an account via
`app.modules.auth.cli create-user`, log in and use `POST /api/organizations` to
create its organization and OWNER membership before creating restaurants. For
staff accounts, provision them first and have an Owner create their memberships.
See [API policies and demonstration](../api/tenancy.md).

## Database acceptance

Configure `TEST_DATABASE_URL` with a database name ending in `_test`. The checker
creates and removes only its own disposable databases:

```powershell
backend/.venv/Scripts/python.exe scripts/check-tenancy-migration.py --run-tests
backend/.venv/Scripts/python.exe scripts/migrate-test-db.py
backend/.venv/Scripts/python.exe scripts/run-browser-tests.py
```

The checker covers clean/previous-head upgrades, no model drift, legacy account
and order snapshot preservation, explicit bootstrap idempotence, and disposable
downgrade/re-upgrade. The backend suite includes cross-tenant direct/nested reads
and writes, list/count scoping, branch assignment restrictions, Employee status
and mixed-field rules, Manager self-promotion denial, last-owner protection,
immediate revocation/role changes, owner creation, atomic staff validation, safe
audit facts and rollback on audit failure. Browser coverage includes the kitchen
controls and direct forbidden API calls. On 2026-10-02, **231 backend tests and
13 Chromium tests passed**. Clean and previous-head upgrades, model drift checks,
bootstrap idempotence, and disposable downgrade/re-upgrade all passed. Test and
restore databases created for this verification were removed afterward.

Without PostgreSQL, `scripts/validate.ps1 -SkipDatabase` runs unit tests and skips
database-backed browser tests. Lint, type checks, build and secret scanning still
run.

## Rollback

Prefer retaining the additive schema while investigating. The previous API
version has unscoped authorization and can create null restaurant IDs, so it
cannot safely run against live tenant data or the new non-null constraint.
Keep writers stopped during rollback. Downgrading from `94d8f2c5b013` to
`83c7e1b4a902` removes organization numbers, permits null scope and multiple
memberships again; tenant rows/audit survive. Downgrading further to
`72bd03a1f901` deletes tenancy and audit data and restaurant associations while
retaining auth/catalog/order rows. After actual tenant usage, prefer restoring
the verified backup with a data reconciliation plan. No live downgrade or
restore has been executed by this work.
