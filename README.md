# RestaurantOS

RestaurantOS is an early full-stack restaurant operations project with a
Next.js frontend, a FastAPI API, and PostgreSQL managed locally with Docker
Compose. The current implementation includes restaurant, menu, menu-item, and
order APIs plus an early analytics dashboard. See
[`docs/current-state.md`](docs/current-state.md) for verified limitations.

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

py -3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install --upgrade pip
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt

Push-Location backend
.venv/Scripts/python.exe -m alembic upgrade head
Pop-Location

Push-Location frontend
npm ci
Pop-Location
```

The Compose username, password, and database name are all `restaurantos`.
They are intentionally predictable **local-development defaults** and must not
be reused for a shared, staging, or production environment.

Start the API from the repository root:

```powershell
Push-Location backend
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

In a second terminal, start the frontend:

```powershell
Set-Location frontend
npm run dev
```

Open <http://localhost:3000>. FastAPI documentation is available at
<http://localhost:8000/docs>, and the liveness endpoint is
<http://localhost:8000/health>.

## macOS and Linux setup

Use the same sequence with platform-specific virtual-environment commands:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
docker compose up -d --wait postgres
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
(cd backend && .venv/bin/python -m alembic upgrade head)
(cd frontend && npm ci)
```

Run the API with
`cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000`
and the frontend with `cd frontend && npm run dev`.

## Validation

With PostgreSQL running and dependencies installed, Windows users can run:

```powershell
./scripts/validate.ps1
```

The script validates Compose, installed Python dependencies, tracked files for
secrets, Ruff, the initial mypy schema scope, backend smoke tests, Alembic state
and model drift, ESLint, TypeScript, and the production frontend build. Use
`-SkipBuild`, `-SkipDatabase`, or `-SkipSecrets` only for targeted local work;
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
