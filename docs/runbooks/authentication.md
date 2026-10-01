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
grant a special owner role; all active accounts share the existing workspace.
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
`AUTH_LOGIN_WINDOW_SECONDS=900`; `AUTH_REFRESH_FAMILY_LIMIT=30`,
`AUTH_REFRESH_IP_LIMIT=120`, `AUTH_REFRESH_WINDOW_SECONDS=60`.
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
