# RestaurantOS

RestaurantOS is an early full-stack restaurant operations project with a
Next.js frontend, a FastAPI API, and PostgreSQL managed locally with Docker
Compose. The current implementation includes restaurant, menu, menu-item, and
order APIs plus an early analytics dashboard. See
[`docs/current-state.md`](docs/current-state.md) for verified limitations.

Business APIs require a provisioned account and active organization membership.
Milestone 3 supplies cookie sessions and authentication rate limits. Milestone 4
adds Owner, Manager and Employee capabilities, branch assignments, scoped queries,
owner bootstrap, staff administration and transactional audit facts. Employee
permissions are the kitchen preparation permissions. Backend features follow
`app/modules/<feature>/{service.py,domain/,repo/}`, as with auth.

Milestone 5 adds scoped ingredient inventory, recipes, real stock availability,
and transactional order acceptance. Stock is consumed on acceptance and **never
returned on cancellation**. Manual stock changes and order consumption share
locks and an auditable movement ledger; order creation and stock writes are
retry-safe. See the [inventory](docs/api/inventory.md),
[recipe](docs/api/recipes.md), and [order contracts](docs/api/orders.md), plus
[verification evidence](docs/current-state.md#milestone-5-completion-evidence).
Inspect the actual application database revision before applying migrations;
repository head and historical local database observations are separate facts.
The [current-state evidence](docs/current-state.md) records dated observations
and the issue #37 application-database incident.

See the [role/API contract](docs/api/tenancy.md) and
[cutover runbook](docs/runbooks/tenancy.md). Local database acceptance and live
cutover completed on 2026-10-02: restaurant 1 belongs to organization 1, and the
sole existing user is its Owner. See [verification evidence](docs/current-state.md#milestone-4-completion-evidence).

Milestone 7 caches scoped menu fields for at most ten seconds of source age at
lookup, while permissions and stock remain live. Authentication uses Redis
admission with stricter process-local outage limits. See the
[cache contract](docs/api/catalog-cache.md) and [Redis operations](docs/runbooks/redis-cache.md).

The retained local benchmark (four menus/160 items, 1,000 attempts per cell,
three repetitions, concurrency 1/10/25/50) shows warm SQL rates about 8.3–16.6%
below the corrected historical uncached baseline. Warm median P95s were
14.0–90.2% higher. A current uncached control shows mixed latency changes and
substantial repetition variation; these serial observations do not establish a
consistent speedup. Cold, warm, mixed-write, Redis outage/restart, query/hit/error
metrics and exact environment/revisions are in the
[measured report](docs/milestone7/performance-milestone7.md) and
[current control](docs/milestone7/performance-milestone7-control.md).
Dashboard caching remains deferred: its [measured prototype](docs/milestone7/performance-milestone7-dashboard.md)
saves about 40% of queries but retains old aggregates after a permitted order
delete until expiry. Milestone acceptance awaits the remaining
verification evidence recorded in [issue #27](docs/milestone7/verification-milestone7-issue27.md).

Milestone 8 T1–T3 record committed events and required deliveries in business
transactions. T4 adds standalone Redis Streams relay/recovery; T5 adds atomic
consumer execution, bounded retries and trusted operator status/inspect/replay.
T6 installs daily completed-sales projection, deletion tombstones and scoped
operator reconciliation; see the [projection contract](docs/api/analytics-projection.md).
T7 installs revisioned alert history/current state, deduplicated notification
stubs, and order/menu diagnostic records; see the
[alert projection contract](docs/api/alert-projection.md). API writes do not
depend on Redis publication or worker availability. See the
[worker runbook](docs/runbooks/event-worker.md) and
[T5 verification](docs/milestone8/verification-milestone8-issue35.md).
T6 adds migration `a936d8e4c021`; T7 adds `b2c7d9a41e63`. Validation does not
migrate the application database.

T8 adds trusted scoped `initialize` and `analytics-rebuild` commands, atomic
legacy analytics/baseline initialization and retained database-role provenance.
See the [backup/cutover/rebuild runbook](docs/runbooks/event-maintenance.md).
Its additive migration is `c3d8e1f52a74`; application cutover remains a separate
explicit operation. Reruns preserve resolved baselines, queued events and receipts.

T9 exposes scoped active alerts and all episode history on the inventory page.
Current stock fences stale projected alerts; history preserves opening snapshots
and baseline provenance. Visible pages refresh every 15 seconds without resetting
editors, retain clearly marked stale data on failures, and clear protected data
when access is lost. See the [alert read contract](docs/api/alert-projection.md).

Milestone 8 T11 adds an isolated [freshness benchmark](docs/testing/event-freshness-benchmark.md)
and [retained results](docs/milestone8/performance-milestone8.md). In three paced
runs at four events/second, pooled P95 was 16.268s for analytics, 18.168s for alerts
and 17.352s for the sink. At two events/second, P95 was below five seconds but
two effects still took 61–64s. The faster 16-events/second cell reached 121.475s.
All 1,980 measured effects completed correctly with no charged retries/failures;
these results do not establish consistent five-second freshness or deployment
capacity. All ten full local gates passed; final PR CI and M8 acceptance remain
open. See the [issue #41 review](docs/milestone8/verification-milestone8-issue41.md).

The [2026-10-20 worker-pool follow-up](docs/milestone8/performance-milestone8-worker-db-pool.md)
meets five seconds for all 1,980 measured effects (maximum 2.009s) with the same
workload. It removes a test-mode connection penalty; normal-mode workers already
pooled connections, so this does not establish equivalent production speedup.
See its [verification](docs/milestone8/verification-milestone8-worker-db-pool.md)
for current gates and remaining acceptance boundaries.

## Prerequisites

- Python 3.12 (the supported documentation and CI version)
- Node.js 24 and npm
- Docker Desktop with Docker Compose v2
- PowerShell 7 for the convenient Windows validation command

The Milestone 0 audit was run locally with Python 3.13.15, Node 24.14.1, and
npm 11.11.0. CI intentionally standardizes the backend on Python 3.12.

## Windows quick start

Run these commands from the repository root in PowerShell:

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item frontend/.env.example frontend/.env.local

docker compose up -d --wait postgres redis

$restaurantOsTestDatabase = docker exec restaurantos-postgres psql -U restaurantos -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'restaurantos_test'"
if (-not $restaurantOsTestDatabase) {
    docker exec restaurantos-postgres createdb -U restaurantos restaurantos_test
}

py -3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install --upgrade pip
backend/.venv/Scripts/python.exe -m pip install --require-hashes -r backend/requirements-dev.txt
backend/.venv/Scripts/python.exe scripts/init-auth-env.py

Push-Location backend
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.modules.auth.cli create-user owner@example.test
$env:DATABASE_URL = "postgresql+asyncpg://restaurantos:restaurantos@localhost:5433/restaurantos_test" # pragma: allowlist secret
.venv/Scripts/python.exe -m alembic upgrade head
Remove-Item Env:DATABASE_URL
Pop-Location

Push-Location frontend
npm ci
npx playwright install chromium
Pop-Location
```

The Compose username, password, and database name are all `restaurantos`.
They are intentionally predictable **local-development defaults** and must not
be reused for a shared, staging, or production environment.

Local Redis listens only on loopback port 6379 without persistence. Startup and
`/health` do not require Redis. The restaurant menu-list and menu-item-list
endpoints have tenant-scoped Redis caches with live authorization and a 10-second
absolute age; item stock and recipe availability are read live from PostgreSQL.
Committed catalog writes invalidate their scoped list keys after PostgreSQL
commit; Redis failures are logged and cannot undo a business write. Authentication
uses Redis atomic admission and failure accounting, with stricter process-local
outage limits; PostgreSQL remains session storage. See
[Redis infrastructure](docs/architecture/redis.md) for their behavior and isolated
validation.

Backend tests use `restaurantos_test` and refuse to run unless
`TEST_DATABASE_URL` names a database ending in `_test`. Tests truncate that
isolated database before and after each test.

Start the API from the repository root:

```powershell
Push-Location backend
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000 --no-proxy-headers
```

In a second terminal, start the frontend:

```powershell
Set-Location frontend
npm run dev
```

Open <http://localhost:3000>. FastAPI documentation is available at
<http://localhost:8000/docs>, and the liveness endpoint is
<http://localhost:8000/health>.
Use `localhost` consistently on both ports; host-only cookies also support server
rendering. Sign in using the account and password entered in the provisioning
command. Secrets stay in the ignored backend `.env` file.
For a fresh setup, create the account's organization first using authenticated
`POST /api/organizations` in FastAPI `/docs`; this creates its OWNER membership.
Then create restaurants. For the existing one-user/one-restaurant database, use
the explicit `bootstrap-existing` command after migrations as described in the
cutover runbook. Newly provisioned staff accounts require an Owner-created
membership before business access is available.


## macOS and Linux setup

Use the same sequence with platform-specific virtual-environment commands:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
docker compose up -d --wait postgres redis
if ! docker exec restaurantos-postgres psql -U restaurantos -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'restaurantos_test'" | grep -q 1; then
  docker exec restaurantos-postgres createdb -U restaurantos restaurantos_test
fi
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-dev.txt
backend/.venv/bin/python scripts/init-auth-env.py
(cd backend && .venv/bin/python -m alembic upgrade head)
(cd backend && .venv/bin/python -m app.modules.auth.cli create-user owner@example.test)
(cd backend && DATABASE_URL=postgresql+asyncpg://restaurantos:restaurantos@localhost:5433/restaurantos_test .venv/bin/python -m alembic upgrade head) # pragma: allowlist secret
(cd frontend && npm ci)
(cd frontend && npx playwright install chromium)
```

Run the API with
`cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000 --no-proxy-headers`
and the frontend with `cd frontend && npm run dev`.

## Validation

With Python 3.12, Node 24, Docker Desktop and Chromium installed, run from the root:

```powershell
./scripts/validate.ps1
```

The command installs the committed dependency locks and runs secret scanning,
separate lint/format/type checks, backend unit and PostgreSQL regression suites,
frontend component/client tests, coverage, clean/legacy migrations, Chromium
journeys, and both production builds. It creates disposable PostgreSQL/Redis
services, database names and browser ports, then cleans up on success or failure.
It does not migrate the application database or reuse developer servers/builds.

Linux and macOS use `backend/.venv/bin/python scripts/validate.py` for the same
gate definitions. `-Gate`, `-NoInstall` and the legacy `-Skip*` switches are
explicit partial runs and cannot count as full milestone validation. CI executes
every gate and requires its aggregate `Milestone 6 acceptance` check.

See [the testing strategy](docs/testing/README.md) for commands, layer boundaries,
the critical-rule map, artifacts, and the explicit Milestone 8 worker/event deferral.
The dated [Milestone 6 verification](docs/milestone6/milestone-6-verification.md) records
execution and the [required-check policy](docs/testing/enforcement.md) with actual
GitHub PR evidence.

## Shutdown

Stop containers without deleting the database volume:

```powershell
docker compose down
```

Deleting the `postgres_data` volume destroys local data and is intentionally
not part of the normal shutdown instructions.
