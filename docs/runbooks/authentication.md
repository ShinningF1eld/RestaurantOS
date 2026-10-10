# Authentication operations

## Local setup

After installing backend requirements, initialize missing local secrets without
printing them or replacing existing non-placeholder values:

```powershell
backend/.venv/Scripts/python.exe scripts/init-auth-env.py
Push-Location backend
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.modules.auth.cli create-user owner@example.test
Pop-Location
```

Copy `.env.example` first on a fresh checkout. The create-user command asks for
a password and confirmation without echo. It does not create an organization or
grant a special owner role. Business access requires an explicit organization
membership; see the [tenancy cutover runbook](tenancy.md) for Owner bootstrap
and staff assignment.
Use 15–128 characters. Never pass passwords on the command line.

Start API with Uvicorn `--no-proxy-headers` for direct local operation. Set
`AUTH_TRUSTED_PROXY_IPS` to exact trusted peer IPs only when deployed behind a
known gateway, and keep Uvicorn's own forwarded-header rewriting disabled so
the application's proxy-chain validation sees the real peer.

Use `localhost` for both frontend and backend. Do not mix it with `127.0.0.1`.
For production use one HTTPS host with explicit gateway routes to the API,
Secure cookies, trusted HTTPS browser origins, SQL echo disabled, and secrets
from secret management. A gateway must distinguish API `/restaurants/{id}/menus`
from frontend `/restaurants/{id}/menu`; preserve API paths and cookie paths.

## Configuration

Required independent secrets: `AUTH_JWT_SECRET` and `AUTH_RATE_LIMIT_SECRET`, <!-- pragma: allowlist secret -->
each at least 32 bytes generated from a secure source. Never reuse example values.
`AUTH_TRUSTED_ORIGINS` is a JSON list of exact browser origins.
`AUTH_COOKIE_SECURE=true` is mandatory in production.

Defaults: `AUTH_ACCESS_SECONDS=600`, `AUTH_SESSION_SECONDS=604800`;
`AUTH_LOGIN_EMAIL_LIMIT=5`, `AUTH_LOGIN_IP_LIMIT=30`,
`AUTH_LOGIN_WINDOW_SECONDS=60`, `AUTH_LOGIN_IP_WINDOW_SECONDS=900`;
`AUTH_REFRESH_FAMILY_LIMIT=10`, `AUTH_REFRESH_IP_LIMIT=100`,
`AUTH_REFRESH_WINDOW_SECONDS=60`. The email-limit setting now controls the
normalized email/source-IP pair, rather than an email-global bucket. Update older
local environment files explicitly; ignored files are not rewritten automatically.
`AUTH_LOCAL_MAX_ENTRIES=10000` is a finite development default. Measure per-entry
memory, available RAM, outage workload and process count before production sizing;
this default is not a measured production capacity recommendation.
The JWT issuer/audience default to `restaurantos` / `restaurantos-browser`.

Changing the JWT secret invalidates access tokens. Existing refresh families can
issue new access tokens unless revoked: to respond to signing-key compromise,
also revoke affected/all server-side families under controlled maintenance.
Changing the rate-limit secret resets effective rate buckets; avoid routine rotation.

## Disable and cleanup

From `backend`:

```powershell
.venv/Scripts/python.exe -m app.modules.auth.cli disable-user owner@example.test
.venv/Scripts/python.exe -m app.modules.auth.cli cleanup --batch-size 500
```

Disable revokes the account's sessions. Cleanup removes expired session families
and rate buckets in bounded batches. Run cleanup periodically through an operator
job; no scheduler is introduced here. Retain consumed refresh digests until
absolute family expiry so replay remains detectable.

Redis limiter entries expire automatically. PostgreSQL limiter history is retained
without runtime counter writes; cleanup still handles its expired legacy rows.
A deadline/cancellation during commit can leave an undisclosed session family
temporarily stored. The row alone grants no access; normal absolute expiry and
bounded family cleanup remove it and its refresh digests. Investigate
`auth_commit_uncertain` events using request IDs and safe `reason`/`process_id`
fields; never collect credentials.

Redis failures immediately activate stricter local enforcement without PostgreSQL
limiter fallback. Probes occur every five seconds, requiring three successful
atomic limiter probes for recovery. Live local history remains enforced through
recovery. Multi-process outage quotas are independent; restart loses history.

### Limiter outage and recovery operations

The [Redis operations guide](redis-cache.md) combines catalog/limiter tuning,
quotas, failure diagnostics and accepted limitations. Dated measured performance
and completion evidence is tracked in [issue #27](../milestone7/verification-milestone7-issue27.md).

The request discovering a Redis failure immediately uses local admission. Later
requests bypass Redis until the five-second probe cooldown expires. One request
owns the bounded atomic admission/release probe; concurrent requests keep using
local limits without waiting for it. Three consecutive successful probes restore
shared mode. An overlapping failure invalidates a probe started before that
failure. A failed probe resets stability without clearing local history. Recovery
uses an owned limiter operation, not `PING`; catalog health is independent.

Watch structured `auth_limiter_degraded`, `auth_limiter_recovering`,
`auth_limiter_healthy` and `auth_limiter_probe_failed` events. Each includes
`process_id`, a safe `reason` and `duration_seconds` since the outage began.
Recovering is logged on the first stable probe, and a subsequent failure records
the transition back to degraded. Repeated skipped requests produce no limiter
logs. Inspect events by process to identify flapping; never collect identifiers,
credentials or raw driver exceptions. Redis command/probe rejection cannot prove
recovery and uses the same local policy as a transport failure.

At `AUTH_LOCAL_MAX_ENTRIES`, new keys receive generic 429 with Retry-After; live
entries are never evicted. Login needs up to two entries, while refresh uses IP
and known-family entries. Expired failures and ten-second reservations are
cleaned during admission/finalization, including extended outages. Recovery keeps
surviving local buckets enforced alongside Redis; new keys use Redis, and normal
expiry frees local capacity. Restarting an API to clear limits deliberately loses
that process's history. Adding processes multiplies outage quotas. Redis's
nonpersistent restart loses its own shared history. These are accepted limits,
not a global outage security guarantee; PostgreSQL counters are never a fallback.

Reproduce local bucket allocation measurements without services:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/measure-auth-local-memory.py --entries 10000
```

Python 3.12.13 on Windows measured 760.1, 953.8, 1526.8 and 6718.8 retained Python
bytes per full bucket at quotas 3, 5, 10 and 50, respectively (2026-10-10).
Ten thousand fully occupied 50-attempt buckets retained 67,188,352 bytes (about
64.1 MiB). This is allocation evidence, not total process RSS or a recommended
production cap: allow additional runtime, temporary cleanup, in-flight request
and allocator overhead. Measure on the deployment runtime, budget RAM per API
process, account for expected distinct outage pairs/IPs/families and process
count, then explicitly configure a finite cap. Keep the development default
until deployment sizing is performed; no deployed environment exists here.

If refresh fails after a lost network response, sign in again. Never replay an
old refresh token to "recover" a response. If auth storage is unavailable, issuance
fails with 503; restore PostgreSQL rather than bypassing auth or throttling.

## Verification

Prepare `TEST_DATABASE_URL` for an isolated existing database ending in `_test`.
Stop local servers on ports 8000 and 3000 before browser tests.

```powershell
backend/.venv/Scripts/python.exe scripts/migrate-test-db.py
Push-Location frontend
npx playwright install chromium
Pop-Location
./scripts/validate.ps1
```

Validation includes lint/type checks, migrations/model drift, PostgreSQL tests,
frontend production build and real Chromium sessions. `-SkipBrowser` is available
for targeted checks; `-SkipBuild` requires an existing current build if browser
tests still run. CI provisions independent backend and browser databases.

## Rollback

Auth schema changes are additive; operational restaurant/order data is untouched.
Back up before any destructive downgrade. Dropping auth tables deletes accounts
and sessions. Returning to pre-auth application code restores anonymous business
access: block external traffic during that rollback. Prefer a forward fix.

Never include cookies, password input, hashes, or signing secrets in bug reports.
Use request IDs, status codes and sanitized timestamps to diagnose failures.
