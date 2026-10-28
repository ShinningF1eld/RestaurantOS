# Production application images

`backend/Dockerfile` uses dependency/runtime stages on the same pinned Python 3.12
base. It installs binary wheels from the hash-locked `backend/requirements.txt`,
without bytecode, into a prefix copied to the runtime. Missing platform wheels
fail the build rather than resolving new versions or compiling source packages.
It copies the application
and Alembic migration files, runs as UID/GID 10001, and starts Uvicorn directly.
The API explicitly uses `--no-proxy-headers` and has an HTTP `/health` check.
Its startup command does not run Alembic;
database migrations remain an explicit operation.

API and worker must use the exact same built image ID/digest. The worker command
is `python -m app.worker`; override the API healthcheck with `--no-healthcheck`
(Compose `healthcheck: { disable: true }`) for that container. This is not a
worker-progress health signal. The image checker imports the real worker
entrypoint without configuration or services to verify packaging; durable worker
progress and shutdown are exercised through the later S1 stack.

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

The post-start schema snapshot is read through the production container's
verified database connection, alongside `current_database()`. The checker rejects
a database-name mismatch and retains every returned table for the no-migration
assertion. It does not open a fresh runner connection while PostgreSQL is
temporarily attached to the smoke bridge. Docker may change a container's default
gateway when its networks change; the initial native ARM run failed at that
runner reconnection, although routing as the exact cause was not established.
See [Docker networking](https://docs.docker.com/engine/network/).

Set `TEST_DATABASE_URL` to a dedicated PostgreSQL database name ending in
`_test`. When PostgreSQL runs in a local `restaurantos-m6-*` Compose project,
pass its container ID with `--postgres-container`. The checker attaches that service temporarily to
its private smoke network with gateway priority -1, preserving the original
gateway and host cleanup connection, uses a unique alias on port 5432, then disconnects it
before removing the network. The PostgreSQL service stays running. The shared
validation command supplies this ID for its local Compose services. For an
externally published service such as CI, omit the option; the image connects
through `host.docker.internal`, with a `host-gateway` mapping on Linux.

The local-service attachment requires Docker Engine/CLI 28 or newer for
`docker network connect --gw-priority`. An unsupported daemon fails the check
rather than falling back to an attachment that can change database routing.

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5432/restaurantos_test" # pragma: allowlist secret
& .\backend\.venv\Scripts\python.exe .\scripts\check-backend-image.py --help
& .\backend\.venv\Scripts\python.exe .\scripts\check-backend-image.py
```

For a running local `restaurantos-m6-*` Compose PostgreSQL service, obtain its
ID with `docker compose --project-name <project> -f docker-compose.test.yml ps -q postgres`
and pass it as `--postgres-container <ID>`.

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

## Standalone frontend image

`frontend/Dockerfile` has dependency, builder and runtime stages on a pinned
official Node 24 Debian slim image. `npm ci` installs the committed lock without
version resolution. Next.js standalone output supplies the server and traced
dependencies; `.next/static` and `public` are explicitly copied. The runtime runs
as the base image's `node` user, starts `node server.js` on port 3000, and defines
a homepage liveness check. It does not require the API to render that page.
The server cache directory is writable by `node`; the smoke test uses a read-only
root filesystem because the tested pages need no runtime disk cache.

The builder fixes `NEXT_PUBLIC_API_URL=/backend`; browser URLs are embedded at
build time. Supply private `API_URL=http://api:8000` at runtime in the later stack.
Do not supply credentials or private API origins as build args. Changing a runtime
public variable cannot reconfigure built browser bundles. The same image can be
promoted between environments using `/backend` routing. Ordinary host development
builds still use their local environment examples.

The frontend `.dockerignore` excludes local dependencies/output, tests, environment
files, npm credential configuration, keys and diagnostics. Neither image copies
the developer's local environment file. Backend secrets remain runtime-supplied.

```powershell
docker build --pull --tag restaurantos-frontend:m9 --file frontend/Dockerfile frontend
backend/.venv/Scripts/python.exe scripts/check-frontend-image.py
```

The frontend checker builds and inspects the image, verifies Node 24/non-root
execution, standalone/public/static assets, the `/backend` browser bundle prefix,
and absence of private files and development tooling in the runtime. It starts
a restricted container on a random loopback port with an intentionally unavailable
runtime API, verifies homepage/login/public assets and linked static assets, and
executes the health command. Cleanup removes only its uniquely named container
and verifies removal, including with `--inject-failure-after healthy`.
It never connects to the application database. These are packaging/liveness
checks, not HTTPS/authentication/SSR tenant-isolation proofs.

The shared `image` gate now requires **both** checkers; its name and ten-gate
aggregate remain unchanged. Unit policy tests verify both are mandatory and
failure propagates. Real new-head CI and hosted acceptance remain separate
evidence. Backend-static also checks the image scripts themselves.

## Platform verification

Both checkers print image ID, OS/architecture and byte size, and accept
`--platform linux/amd64` or `--platform linux/arm64` for explicit build/run checks:

```powershell
backend/.venv/Scripts/python.exe scripts/check-backend-image.py --platform linux/arm64
backend/.venv/Scripts/python.exe scripts/check-frontend-image.py --platform linux/arm64
```

The backend command requires the disposable PostgreSQL setup described above.
Run on an ARM64 Docker host for native evidence; Docker Desktop emulation can
test packaging but does not establish native ARM performance or OCI capacity.
Base manifest support alone is not application runtime proof. Images are built
locally, never pushed. No image-size reduction is claimed without measurements;
multi-stage packaging separates build contents.
