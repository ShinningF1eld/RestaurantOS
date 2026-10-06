# Backend production image

`backend/Dockerfile` builds the API from Python 3.12 and installs only the
hash-locked runtime set in `backend/requirements.txt`. It copies the application
and Alembic migration files, runs as UID/GID 10001, and starts Uvicorn directly.
The image has an HTTP `/health` check. Its startup command does not run Alembic;
database migrations remain an explicit operation.

`backend/.dockerignore` excludes environment files, local keys, virtual
environments, test and development dependency files, tests, caches, coverage,
and generated data. Docker receives the `backend/` directory as its build
context, and the Dockerfile copies only runtime files and the runtime lock.
Database URLs and signing secrets are supplied at container startup and are not
stored in the image configuration.

## Build and smoke check

The image check builds from the current source using `docker build --pull` and
pins `python:3.12-slim` to the upstream digest recorded in `backend/Dockerfile`,
inspects the configured user and image environment, and checks that no local
environment files, tests, development locks, virtual environments, or generated
artifacts appear under `/app`. It then allocates a unique PostgreSQL database
through `TEST_DATABASE_URL`, starts the production image with fresh signing
secrets, secure cookies, and an HTTPS trusted origin, and publishes the API on a
random loopback port. The runner verifies `/health`, connects from the image to
the disposable PostgreSQL database with `SELECT 1`, and confirms the image did
not create tables or an `alembic_version` row. The container and its unique
network are removed in a `finally` cleanup path; the database helper drops its
allocated database on success and failure.

Set `TEST_DATABASE_URL` to a dedicated PostgreSQL database name ending in
`_test`. Local Docker Desktop runs can use a loopback-published PostgreSQL port.
The image connects through `host.docker.internal`; on Linux the runner adds a
`host-gateway` mapping for that name.

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5432/restaurantos_test" # pragma: allowlist secret
& .\backend\.venv\Scripts\python.exe .\scripts\check-backend-image.py --help
& .\backend\.venv\Scripts\python.exe .\scripts\check-backend-image.py
```

Pass `--image restaurantos-backend:m6` to select a tag; the default is the same.
The command builds and tests locally and does not push to a registry. To exercise
cleanup after the container is healthy, use
`--inject-failure-after healthy`; it must fail while still removing the
container, network, and allocated database.

To review the upstream base image digest before a deliberate pin update, pull
the human-readable tag and inspect its repository digest:

```powershell
docker pull python:3.12-slim
docker image inspect --format '{{json .RepoDigests}}' python:3.12-slim
```

Update the digest in `backend/Dockerfile` only after review, then rebuild and
rerun the image smoke check. An example manual build is:

```powershell
docker build --pull --tag restaurantos-backend:m6 --file backend/Dockerfile backend
```
