# Local container and HTTPS rehearsal

This is Milestone 9 S1 step #3: a local synthetic stack, not an OCI deployment.
It uses its own generated Compose project, PostgreSQL database, volumes, secrets
and certificate authority. Developer Compose and its application DB are untouched.
The helper rejects SSH/TCP Docker endpoints; use the local Linux-container socket.
Use Python from the installed backend environment, Docker Desktop's Linux engine
and committed dependency locks. No new dependencies are needed.

## Start the stack

From the repository root:

```powershell
backend/.venv/Scripts/python.exe scripts/local-gateway.py init
backend/.venv/Scripts/python.exe scripts/local-gateway.py build
backend/.venv/Scripts/python.exe scripts/local-gateway.py migrate
backend/.venv/Scripts/python.exe scripts/local-gateway.py up
backend/.venv/Scripts/python.exe scripts/local-gateway.py check --restart
backend/.venv/Scripts/python.exe scripts/local-gateway.py status
```

On Linux use `backend/.venv/bin/python`; route inspection needs the `ip` utility.
`init --port 9443` chooses a different loopback port. Initialization refuses an
existing `.local-gateway` directory, so it cannot overwrite secrets. Do not run
initialization again for an existing rehearsal; use `up` to resume it.

`build` records exact application image IDs in the ignored state manifest. API,
worker and explicit maintenance commands use the same backend identity. `migrate`
is a deliberate operation and rejects running, paused or restarting API/worker
writers. `up` checks the actual DB revision against the built image's Alembic head;
it never migrates. For subsequent schema work, stop the stack first, build, migrate
explicitly, then start. These local guards do not implement production release,
backup or interrupted-migration recovery procedures.
Compose actions refuse missing application image identities rather than pulling
an implicit fallback image. After editing a mounted configuration file, use
`down`/`up` to reload it deliberately; existing settings are not silently replaced.

Each helper invocation holds a local operation lock. If a process is killed,
inspect the PID in `.local-gateway/operation.lock` and actual container/schema
state before removing that stale lock. Never remove a live operation's lock.
The helper rejects foreign project markers and any configured DB except
`postgres:5432/restaurantos_gateway_test` with the expected driver/user.

## How requests travel

`deploy/local/compose.yaml` runs six normal services; its maintenance service is
an explicit one-shot tools profile. Only Caddy publishes a port:
`127.0.0.1:8443 -> 443`. HTTP/port 80 and HTTP/3 are not exposed in this local
rehearsal. Caddy sends frontend paths to Next.js and strips `/backend` for FastAPI.
Backend slash redirects are normalized back to HTTPS and `/backend`; API docs,
ReDoc and the schema are deliberately closed at the gateway. Internal backend
URLs and the existing developer endpoints are unchanged.

Browser bundles use `/backend`; SSR uses private `http://api:8000` and only the
access cookie. Refresh cookies are scoped to `/backend/auth`. Exact trusted origin
includes the selected HTTPS port. Caddy replaces forwarded client/protocol/host
headers and removes `Forwarded`/`X-Real-IP`; Uvicorn proxy rewriting stays disabled.

Separate bridges connect Caddy/frontend, Caddy/API, frontend/API and data services.
Only API, worker and explicit maintenance join the data network with PostgreSQL
and Redis. The fixed proxy network is checked against host routes and existing
Docker subnets at initialization. Both peers have explicit addresses so the API
cannot dynamically consume the Caddy address. Only Caddy's exact address is trusted;
conflicts must fail, never silently choose a new address after initialization.
Host/VPN route changes require a fresh conflict review.

## TLS trust and accounts

Caddy uses its own local CA, stored in its dedicated volume. `up` exports only
the public root certificate to `.local-gateway/root.crt`; it does not install it
into any host or browser trust store. The checker verifies certificates and
hostnames using this CA, with Secure cookies enabled and no TLS verification bypass.

```powershell
curl.exe --cacert .local-gateway/root.crt https://localhost:8443/backend/health
```

For interactive browser use, explicitly trust that root in an isolated test
browser/profile using your browser's certificate-management procedure. Do not use
your normal developer login profile: localhost cookies are scoped by hostname,
not port, and could collide with existing localhost sessions. Do not distribute
the CA private key or use this local CA as a public deployment certificate.

Checks create unique synthetic accounts, organizations, restaurants and menus.
They retain that synthetic data for persistence checks and do not print credentials.
Each full check consumes five failed-login IP attempts to prove header spoofing
does not bypass existing quotas; do not loop checks to bypass a resulting 429.
Ordinary success login/refresh semantics remain unchanged.

To practice manual provisioning, take the API container name from `status`, then:

```text
docker exec -it <api-container-name> python -m app.modules.auth.cli create-user learner@example.test
```

The existing CLI prompts privately. Use an operator-generated password of at least
15 characters; then follow the [auth](authentication.md) and [tenancy](tenancy.md)
runbooks for first organization/membership provisioning. This does not introduce
registration or password reset. The local PostgreSQL bootstrap role owns its
rehearsal cluster; production database-role hardening is not established here.

## Persistence, secrets and limits

API startup health now uses the bounded database [`/ready` check](../api/health.md).
The frontend waits for this check; `/health` remains process liveness. Neither
endpoint applies migrations or checks worker progress. The explicit revision
check and migration procedure above still apply.
Rebuild with `scripts/local-gateway.py build` before `up` when using images built
before this endpoint was added; those older API images cannot serve `/ready`.
Startup waits explicitly on the gateway/API/frontend/database services, then
starts and checks the worker process separately. This avoids Compose 2.38's
`--wait` bug for a deliberately disabled inherited HTTP healthcheck. Worker
progress is still established by the real receipt/effect check, not process
liveness alone. See [the upstream issue](https://github.com/docker/compose/issues/13522).

Normal shutdown:

```powershell
backend/.venv/Scripts/python.exe scripts/local-gateway.py down
```

It removes this project's containers/networks and retains PostgreSQL/Caddy volumes.
There is intentionally no volume-deletion/reset helper. `check --restart` performs
that same down/up cycle and verifies session/tenant/catalog data, SSR and CA identity
survive. Reboot/complete-host-loss recovery are later tests, not inferred from this.

Secrets live only in ignored `.local-gateway` files, never image build arguments.
On Windows the directory ACL allows the current user, SYSTEM, administrators and
owner rights; on Linux it is mode 0700. The bind-mounted settings/config/password
files are readable by container UIDs, protected on the host by that private
directory. This is local runtime custody, not production host-secret rotation.

The stack applies the design's testing memory/PID ceilings, CPU shares and bounded
JSON logs. Node heap is 320 MiB; PostgreSQL has 30 connections and 128 MiB shared
buffers. API pool is explicitly 5 connections, zero overflow, five-second checkout;
worker retains its six-connection pool. New API pool settings preserve previous
host defaults (5/10/30) unless configured; tests still use NullPool.
Redis requires a generated password, has 128 MiB maxmemory/noeviction and no disk
persistence. PostgreSQL retains authoritative events/receipts. Redis loss recovery,
full-memory failure handling and native ARM capacity still need their later tests.

The checker inspects real container limits/network membership/port mappings and
pool/Redis configuration; it also verifies TLS, cookies, origin enforcement,
forwarding-header allowance behavior, a protected SSR page and a durable worker
receipt. The separate [Chromium gateway matrix](../testing/gateway-browser.md)
now exercises step #4 in a fresh disposable project and leaves this persistent
rehearsal alone. Its certificate-key exception is confined to its test browser.
See the [gateway evidence](../milestone9/verification-milestone9-gateway.md).

Configuration references: [Caddy proxy headers](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[local TLS](https://caddyserver.com/docs/caddyfile/directives/tls), and
[Compose networking](https://docs.docker.com/compose/how-tos/networking/).
