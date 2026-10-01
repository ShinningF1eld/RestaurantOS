# RestaurantOS

RestaurantOS is an early full-stack restaurant operations project with a
Next.js frontend, a FastAPI API, and PostgreSQL managed locally with Docker
Compose. The current implementation includes restaurant, menu, menu-item, and
order APIs plus an early analytics dashboard. See
[`docs/current-state.md`](docs/current-state.md) for verified limitations.

Business APIs require a provisioned account. Milestone 3 adds secure login,
rotating browser sessions, logout, and authentication rate limits in the new
`backend/app/modules/auth` feature module. Accounts currently share the workspace;
tenant permissions are Milestone 4. See the [auth runbook](docs/runbooks/authentication.md)
and [API contract](docs/api/authentication.md).

Milestone 4's [tenancy schema expansion](docs/architecture/tenancy-schema.md)
defines Owner, Manager, and Employee memberships and restaurant assignments.
This is a schema-only foundation; tenant authorization and owner bootstrap are
still pending, and existing business APIs continue to share the workspace.

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

docker compose up -d --wait postgres

$restaurantOsTestDatabase = docker exec restaurantos-postgres psql -U restaurantos -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'restaurantos_test'"
if (-not $restaurantOsTestDatabase) {
    docker exec restaurantos-postgres createdb -U restaurantos restaurantos_test
}

py -3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install --upgrade pip
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
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

## macOS and Linux setup

Use the same sequence with platform-specific virtual-environment commands:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
docker compose up -d --wait postgres
if ! docker exec restaurantos-postgres psql -U restaurantos -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'restaurantos_test'" | grep -q 1; then
  docker exec restaurantos-postgres createdb -U restaurantos restaurantos_test
fi
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
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

With PostgreSQL running and dependencies installed, Windows users can run:

```powershell
./scripts/validate.ps1
```

The script validates Compose, installed Python dependencies, tracked files for
secrets, Ruff, full-backend mypy, backend regression tests, Alembic state
and model drift, ESLint, TypeScript, the production frontend build, and the
real Chromium authentication/sale suite.
Stop development servers on ports 3000 and 8000 before full validation. Use
`-SkipBuild`, `-SkipDatabase`, `-SkipBrowser`, or `-SkipSecrets` only for targeted local work;
CI runs every underlying gate independently.

Equivalent individual commands are recorded in
[`docs/current-state.md`](docs/current-state.md) and
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Shutdown

Stop containers without deleting the database volume:

```powershell
docker compose down
```

Deleting the `postgres_data` volume destroys local data and is intentionally
not part of the normal shutdown instructions.
