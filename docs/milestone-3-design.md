# Milestone 3 implementation plan: authentication and feature modules

Status: Implementation plan executed on 2026-09-30; final verification evidence
is recorded in `docs/current-state.md`. Scope follows Milestone 3 of
`RestaurantOS_Master_Roadmap.md`.

## 1. Outcome and scope

Deliver email/password login, authenticated business APIs, renewable browser
sessions, refresh replay detection, logout, account-status enforcement, and
login/refresh rate limits. Preserve the existing restaurant-to-sale workflow.

Start the gradual move from layer-first folders to feature-first modules with
`app/modules/auth`. Existing modules can coexist with this structure. Catalog
is the next migration candidate, not a prerequisite for authentication.

Defaults for this milestone:

- Provision users through an explicit CLI command; no public registration yet.
- Authenticated users share the existing workspace. Organization ownership,
  restaurant assignments, and capabilities belong to Milestone 4. Authentication
  alone does not provide tenant isolation; do not advertise a multi-tenant release.
- Include current-session logout. Defer a user-facing session-management screen,
  logout-all endpoint, password reset/email delivery, email verification, MFA,
  OAuth/SSO, and public registration.
- Keep existing business URLs and response contracts. Add `/auth/login`,
  `/auth/refresh`, `/auth/logout`, and `/auth/me`; version all routes in a separate
  coordinated change rather than mixing URL migration with authentication.
- Use cookie-based browser credentials for both access and refresh tokens to
  support the existing mix of browser and server-rendered API requests.

## 2. Repository findings and constraints

Inspected the roadmap, backend wiring/services/repos/models/tests/migrations,
frontend API callers, validation script, and applicable frontend AGENTS.md.
The working tree was clean before adding this document. Existing checks were
not rerun during this planning task; historical pass counts are not fresh results.

| Existing implementation | Consequence for this milestone |
|---|---|
| `app/routers`, `services`, `repositories`, `domain`, `schemas`, `db/models` | Add a feature module without a repository-wide move. |
| Service writes use `async with session.begin()` | Authentication must not leave an implicit transaction on the business session. |
| `get_db` rolls back outstanding transactions at teardown | Reuse existing lifecycle rules; repositories never commit. |
| FastAPI registers business routers centrally | Protect all business routers at composition time, including analytics. |
| Shared errors map to `{ "detail": ... }` | Extend auth status mapping without changing existing business error bodies. |
| Alembic imports `app.db.models` to populate metadata | Explicitly register new module models against the one existing Base. |
| PostgreSQL fixtures truncate a hardcoded table list | Add auth/rate-limit tables to cleanup and authenticated test fixtures. |
| Strict mypy overrides enumerate legacy packages | Include `app.modules.*` in strict typing. |
| Frontend API helpers use independent `fetch` calls | Add a shared transport and migrate every helper. |
| Restaurant layout, menu, orders, dashboard use server reads | Explicitly forward access credentials; browser-only refresh code is insufficient. |
| CORS has one hardcoded localhost origin | Configure exact origins and a matching CSRF policy. |
| Four migration files, including order lifecycle/history | Append migrations after the actual current head; do not alter old revisions. |

## 3. Feature-first architecture

Milestone 3 layout:

```text
backend/app/
  main.py                         # composition and router protection
  core/                           # shared settings, logging, base errors
  db/                             # one engine/session factory and declarative Base
  http/                           # shared HTTP middleware/error mapping
  modules/
    __init__.py
    auth/
      __init__.py
      router.py                   # HTTP bodies, cookies, statuses
      schemas.py                  # API request/response models
      dependencies.py             # current principal and auth read session
      service.py                  # login/rotate/logout orchestration
      domain/
        __init__.py
        principal.py              # immutable authenticated identity
        policies.py               # session/account validity and expiry rules
        errors.py                 # auth failures without HTTP dependencies
      repo/
        __init__.py
        models.py                 # User, AuthSession, RefreshToken, rate buckets
        users.py                  # identity lookup and provisioning persistence
        sessions.py               # token lookup, locks, rotation, revocation
        rate_limits.py            # atomic PostgreSQL rate counters
      security.py                 # library-backed hashing/JWT/random token adapters
      rate_limit.py               # limiter policy and narrow storage interface
      cli.py                      # create/disable user and expired-state cleanup
  routers/                        # existing feature code remains temporarily
  services/
  repositories/
  domain/
  schemas/
```

The eventual catalog shape is `modules/catalog/{router.py, schemas.py,
service.py, repo/, domain/}`. Do not manufacture domain objects for simple CRUD;
introduce domain files when there are actual policies to own. Use the same
pattern for orders, restaurants, and analytics when those features are touched.

Rules:

1. Router -> service -> domain/repo/security adapter. Domain code has no FastAPI,
   SQLAlchemy, cookies, or environment reads. Repositories have no HTTP knowledge.
2. Keep the service layer. Feature-first organization changes where layers live,
   not who owns business rules and transactions.
3. Auth repos use the existing shared Base/session infrastructure. No separate
   auth database, generic repository framework, or new unit-of-work framework.
4. Other features consume an immutable `AuthenticatedPrincipal` through the
   auth dependency; they do not query auth tables or import auth repo internals.
5. Model-registration imports are explicit at application/Alembic composition
   points, not side effects of importing routers. Register each model once.
6. New auth code goes only in the new module. Shared plumbing belongs in core,
   db, or http only when it genuinely serves multiple features.
7. Later catalog migration is a dedicated behavior-preserving change: move its
   service, repo, schemas and routes; update callers/tests; handle existing
   order/analytics references to catalog ORM models explicitly. No table rename
   or duplicate ORM declaration just because a Python file moves.

## 4. Authentication and browser contract

### Identity and password handling

- Normalize email consistently on provisioning and login: trim surrounding
  whitespace and apply the documented case-insensitive account identifier policy.
  Enforce uniqueness in PostgreSQL, not only with a pre-insert lookup.
- Store only Argon2id password hashes. Use a maintained library, proposed
  `pwdlib[argon2]`, and PyJWT for JWT signing/verification. Select and pin compatible
  versions during implementation; verify installation and Python 3.12 support.
- Provisioning prompts for passwords without echo; do not accept a password in
  a shell argument or print a generated credential. Define a password policy
  (proposed 15–128 characters, spaces allowed, no silent truncation).
- Run password hashing/verification outside the async event loop with bounded
  concurrency. Validate input sizes and rate limits before expensive hashing.
- Wrong password, unknown email, and disabled account return the same login
  response. Use dummy hash verification for unknown users. Rehash on successful
  login when configured hashing parameters change.

### Token and session defaults

- Access JWT lifetime: proposed 10 minutes. Require and verify `sub`, `sid`,
  `iss`, `aud`, `iat`, and `exp`; include a token-use claim and validate it.
- Fix the allowed algorithm in server configuration, initially HS256 with a
  cryptographically random secret of at least 32 bytes. Never derive the accepted
  algorithm from the supplied token header. Reject malformed and missing claims.
- Refresh token: opaque cryptographically random value with at least 256 bits
  of entropy. Store only a SHA-256 digest with a unique index. This digest is
  suitable for random tokens; passwords still require Argon2id.
- One login creates one session family. Proposed absolute session lifetime is
  seven days; rotation never extends that absolute expiry.
- Each protected request verifies the JWT and checks that its session and user
  remain active. Logout/disable therefore blocks subsequent requests even before
  the access JWT expires. Requests already authorized may finish.
- Never place roles or tenant authorization assumptions in this milestone's JWT.

### Cookies, CSRF, CORS, and deployment topology

- Both token cookies are HttpOnly, Secure in production, host-only (no Domain),
  and SameSite=Lax. Access cookie uses Path=/ so server-rendered pages receive it;
  refresh cookie uses Path=/auth so it is sent only to auth endpoints.
- Local development uses the same hostname (`localhost`) on ports 3000/8000;
  cookies are not port-scoped. Explicit development config permits HTTP cookies.
  Do not alternate `localhost` and `127.0.0.1`.
- Production requires frontend and API on one HTTPS host with a gateway routing
  auth and existing business paths to FastAPI. Separate frontend/API hostnames
  require a new BFF/cookie transport decision; do not broaden cookie Domain as
  an undocumented workaround. Full deployment remains Milestone 9.
- Browser fetches include credentials. CORS uses exact configured origins and
  explicit methods/headers with credentials enabled, never a wildcard origin.
- Enforce an exact trusted Origin and a non-simple custom request header on
  **all unsafe browser operations**, including login, refresh, logout, and
  business writes. Reject missing/untrusted/null Origin for these requests.
  Require JSON where there is a body; CORS preflight does not require login.
  CLI/API examples supply these headers explicitly. CORS alone is not CSRF protection.
- Do not mutate state via GET. Document XSS as a remaining risk: HttpOnly limits
  token extraction but cannot stop malicious same-origin code making requests.
- Auth responses and authenticated server fetches use no-store. Tokens do not
  appear in JSON responses, localStorage, sessionStorage, HTML, URLs, or logs.
- Delete cookies with matching names, paths and attributes on logout/terminal
  session failure. Keep secrets, Cookie/Set-Cookie/Authorization headers, login
  bodies, and validation-error input values out of logs and error responses.

### Endpoints

| Endpoint | Input/credentials | Success | Failure |
|---|---|---|---|
| `POST /auth/login` | JSON email/password, CSRF checks | 200 public user summary; set both cookies | Generic 401; 422 invalid shape; 429 throttled |
| `POST /auth/refresh` | Refresh cookie, CSRF checks | 200 public user summary; rotate cookies | Generic 401; 429 throttled |
| `POST /auth/logout` | Refresh cookie or valid current session, CSRF checks | Idempotent 204; revoke current family and clear cookies | 403 invalid origin/header; DB failure must not claim successful revocation |
| `GET /auth/me` | Access cookie | 200 id, email, public status | 401 invalid/expired/revoked identity |

Keep `{ "detail": "..." }` for errors. Add 401/403/429 mapping as needed,
`Retry-After` for rate limiting, and document cookie auth in OpenAPI. Auth schemas
must never serialize password hashes or token digests.

Protect restaurant, menu, menu-item, order, and analytics routes. Keep `/health`
public. Keep `/api/test` only as a harmless public liveness alias for the current
landing page; remove or disable `/api/test-db` in production. Document whether
docs/OpenAPI are publicly available; they must expose no credentials or data.

## 5. Persistence, transactions, and concurrency

### Tables

| Table | Key fields and constraints |
|---|---|
| `users` | UUID PK, normalized email unique/not-null, password_hash, active/disabled status check, created_at/updated_at UTC |
| `auth_sessions` | UUID PK/family id, user FK/index, created_at, absolute expires_at, revoked_at/reason |
| `auth_refresh_tokens` | UUID PK, session FK/index, digest unique, issued_at, expires_at, consumed_at, optional successor id |
| `auth_rate_limit_buckets` | key digest + window start unique, attempt count, expires_at/index |

Use timezone-aware timestamps and database constraints for validity. Add an index
or constraint preventing multiple unconsumed token rows per family. Retain
consumed token digests until their family's absolute expiry so replay remains
detectable. Cleanup expires sessions/tokens and rate buckets in bounded batches.
No restaurant/order foreign keys or ownership backfills in this milestone.

### Rotation algorithm

1. Rate-limit the request, hash the supplied token, find its token/family.
2. Start a service-owned transaction; lock the family row, then re-read token
   state. Use a consistent lock order in rotation, logout, and disable operations.
3. Reject absent, expired, revoked, or disabled-user sessions.
4. If the token was already consumed, revoke the whole family and commit that
   revocation. Return a failure outcome from the transaction; only then map it
   to HTTP 401. Raising inside the transaction would roll the revocation back.
5. Otherwise mark the old token consumed and insert a successor, preserving the
   family expiry, in the same transaction. Sign the new access token and return
   cookies only after the database commit succeeds.
6. A concurrent second use of the same token is replay and revokes the family.
   Do not introduce a grace period that silently accepts token reuse.

A lost refresh response may require a new login because the client retains a
consumed token. Document this security/availability tradeoff and avoid automatic
refresh retries after ambiguous transport failures.

### Avoid the existing AsyncSession trap

Use a separate short-lived read session inside the current-principal dependency,
return an immutable principal, and close that session before calling the business
handler. Keep `get_db` and existing service write transactions unchanged.

Do not reuse FastAPI's cached business `get_db` dependency for principal lookup:
its SELECT starts an implicit transaction, and the service's subsequent
`session.begin()` would fail. Add a regression test using real authentication
followed by restaurant/order writes. Auth command services own their own explicit
transactions; rate-limit accounting commits independently of login success.

Disable-user and login/refresh must serialize their user-status checks/writes
consistently so concurrent disable cannot create a usable session. Define one
lock ordering (user before family when both are required) and test it.

## 6. Rate limiting without pulling Milestone 7 forward

Use atomic PostgreSQL counters behind a narrow limiter interface for now; do not
ship an in-memory limit that resets per worker. Redis can replace the adapter in
Milestone 7 without changing endpoint policy.

- Proposed initial login limits: 5 attempts per normalized email per 15 minutes
  and 30 attempts per IP per 15 minutes. Count success and failure consistently.
- Proposed refresh limits: 30 attempts per family per minute and 120 per IP per
  minute. Unknown tokens still consume an IP limit.
- These are initial configurable values, not measured capacity claims. Account
  buckets are temporary throttles, not permanent account lockouts.
- Use atomic upsert/increment with concurrent-request tests and Retry-After.
  Document fixed-window boundary bursts and tune after measurement.
- Derive client IP only through a configured trusted proxy chain; never trust
  arbitrary forwarded headers. Persist keyed digests for account/IP bucket keys,
  using a separate environment secret; don't log raw emails or tokens.
- Storage unavailable: return a service-unavailable error for auth issuance,
  never silently bypass limits. Cleanup bounded/expired buckets explicitly.

## 7. Frontend integration

Preserve server-rendered reads. Separate browser and server transports so
server-only credential handling cannot enter client bundles.

1. Add login page, logged-in identity/logout UI, and a session-expired state.
2. Introduce a browser API client with credentials, unsafe-method CSRF header,
   consistent errors and one controlled refresh attempt after a 401. Migrate
   restaurant/menu/menu-item/order/analytics callers, not just the login form.
3. Serialize refresh within a tab and across tabs (Web Locks plus a session
   notification channel). After acquiring the lock, recheck `/auth/me`: another
   tab may already have refreshed. Broadcast only session status, never tokens.
   Test target browser support and provide a safe re-login fallback where
   cross-tab coordination is unavailable.
4. Retry a business request once only after a successful refresh and an explicit
   pre-handler 401. Never retry uncertain writes after network/5xx failures.
   Login/refresh/logout themselves bypass recursive refresh handling.
5. Add a server-only API client that reads the incoming access cookie and forwards
   only that cookie to the fixed configured API origin; never forward arbitrary
   headers/cookies or user-controlled destinations. Use no-store per request.
6. Server-rendered API reads do not rotate tokens: they cannot reliably deliver
   replacement cookies to the browser. On an expired session, redirect to a
   dedicated `/session/renew` page which performs the locked browser refresh and
   returns to a validated local path. On failure go to login. Bound attempts and
   prevent redirect loops/open redirects.
7. Update restaurant layout and menu/orders/dashboard server reads to handle auth
   failure separately from a restaurant 404 or backend outage. Frontend guards
   improve navigation; FastAPI remains the enforcement boundary.
8. On logout clear client user state and invalidate rendered business views;
   notify other tabs. A failed logout must not claim server revocation succeeded.

Before frontend implementation, follow `frontend/AGENTS.md` and read the installed
Next.js guides for cookies, server/client boundaries, redirects, and route
handlers. Do not assume framework APIs from older releases.

## 8. Ordered implementation slices

Each slice includes its tests and must leave the application coherent.

| Slice | Work | Acceptance gate |
|---|---|---|
| 1. Record contracts and establish module | ADR for feature modules/auth transport, module skeleton, config, model registration, mypy scope | Imports and OpenAPI unchanged; existing checks pass |
| 2. Identity storage and provisioning | Additive user/session/token/rate migrations, user CLI, hashing/JWT adapters | Clean and existing DB migration; user CLI; hash/token unit tests |
| 3. Login and me | Login transaction, cookies, limits, CSRF/CORS, principal dependency | Generic failures, active-status checks, JWT expiry/claim validation |
| 4. Refresh and logout | Family locking, rotation, persisted replay revocation, logout, cleanup | Real PostgreSQL replay/concurrency/rollback tests |
| 5. Frontend session flow | Browser/server clients, login, renew, logout, migrate all API callers | Reload, deep-link, expired-access, and multi-tab browser tests |
| 6. Enforce business authentication | Protect all business routers; authenticated fixtures; update smoke flow | Anonymous requests denied; real authenticated sale still completes |
| 7. Release validation and docs | Full checks, migration rehearsal, OpenAPI examples, runbook, roadmap evidence | All required evidence recorded; limitations explicit |

Slices 3–5 are intermediate development states; do not release as completed
authentication while anonymous business access is still enabled. No production
auth-bypass flag is introduced. Catalog's physical move stays a later separate
slice to keep this milestone focused.

## 9. Expected files

New:

- `backend/app/modules/auth/**` and module package initializers.
- New revisions under `backend/alembic/versions/`.
- `backend/tests/unit/auth/`, `backend/tests/integration/auth/`, and auth HTTP
  tests/fixtures; use real PostgreSQL for locking and constraints.
- `frontend/features/auth/`, `frontend/lib/api/client.ts`, a server-only transport,
  `frontend/app/login/page.tsx`, `frontend/app/session/renew/page.tsx`.
- Browser tests and runner config (proposed Playwright) with dependency lockfile.
- `docs/adr/0002-feature-modules.md`, `docs/adr/0003-authentication-sessions.md`,
  `docs/api/authentication.md`, `docs/runbooks/authentication.md`.

Update:

- `backend/app/main.py`, `core/config.py`, shared HTTP errors as required,
  model registry/Alembic wiring, requirements and `pyproject.toml`.
- `backend/tests/conftest.py`, business HTTP characterization/integration tests.
- All `frontend/lib/api/*.ts` helpers and their browser/server call sites;
  frontend login/navigation state, package scripts and lockfile.
- Environment examples, `scripts/validate.ps1`, API smoke script as applicable,
  `.github/workflows/ci.yml`, README, current-state document and master roadmap.

Configuration includes JWT secret/issuer/audience/lifetime, refresh lifetime,
cookie security mode/names, trusted browser origins, trusted proxies, rate-limit
secret/thresholds, and server API origin. Use validated secret types and reject
missing secrets, insecure production cookies, invalid durations, and invalid
production origins at startup. Examples contain placeholders, never working
production credentials. Tests set explicit ephemeral/test-only secrets before
application import. Account for Alembic loading shared settings too.

## 10. Verification matrix

- Password: hash differs from input; correct/incorrect verification; normalized
  duplicate emails rejected; unknown/wrong/disabled login errors indistinguishable.
- JWT: valid, expired, tampered, wrong key/algorithm/issuer/audience, missing or
  malformed claims, incorrect token-use, revoked session, disabled user.
- Refresh: cookie rotates; only digest persisted; consumed token retained;
  replay commits family revocation; successor access/refresh both rejected after
  replay; expiry not extended; DB failure rolls rotation back.
- Concurrency: same-token refresh races revoke family; rotation/logout serialize;
  disable vs login/refresh cannot yield usable credentials; no double successor.
- Logout: current family revoked, another independent login remains valid,
  repeated/missing-cookie logout safe, expired access plus valid refresh works.
- HTTP: every business method rejects anonymous callers; cookies have correct
  production flags; unauthorized origins/missing custom headers rejected;
  preflight works; no-store; 429 Retry-After; no secrets in responses/logs.
- Transactions: authenticated create/update paths do not hit nested/autobegin
  failures; existing business rollback behavior survives authentication.
- Rate limits: concurrent counters work across clients/workers; unknown accounts
  count; windows expire; spoofed proxy headers ineffective; DB outage fails closed.
- Frontend: login -> restaurant -> menu -> order -> completion -> dashboard;
  reload/deep-link restoration; SSR expiry renewal; simultaneous 401s and tabs;
  failed refresh/logout; backend offline vs logged out; no unsafe retry loops.
- Tests preserve negative auth coverage: do not globally bypass the auth
  dependency. Existing HTTP tests use real authenticated sessions where practical.
- Migrations: zero-to-head and current-head-to-new-head on disposable databases,
  existing restaurant/order row counts/history preserved, one head, no model drift.

Run `./scripts/validate.ps1` with the documented PostgreSQL setup, plus the new
browser suite integrated into validation/CI. The existing validation script
upgrades the configured application DB but does not prepare the test DB itself;
explicitly migrate the isolated `_test` database before pytest. Record exact
commands/results and any unavailable gates. Do not infer success from code review.

## 11. Migration and completion policy

Migrations are additive. No password/user seed in Alembic and no change to
existing restaurant ownership. Provision the first account after migration with
the CLI, using an explicit operator action. Preserve existing operational data.

Rehearse downgrade on disposable data only: dropping auth tables destroys users
and sessions. A rollback to pre-auth application code would reopen anonymous
access, so the runbook must block external access during such a rollback and
prefer a forward fix. Do not treat code rollback as a safe authentication rollback.

Milestone 3 is complete when every business route requires active identity,
browser reload renews sessions safely, replay and logout revoke correctly,
limits/CSRF checks are enforced, the original sale workflow passes with real
authentication, migrations/checks pass, and docs describe the remaining shared
workspace limitation. Update milestone status only with reproduced evidence.

## 12. Reference basis

Library choice follows the maintained-library approach in
[FastAPI's JWT guide](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/).
We use its library guidance, not its example as a complete session architecture.

Refresh rotation and replay revocation follow the principles in
[RFC 9700, section 4.14](https://www.rfc-editor.org/rfc/rfc9700.html#section-4.14).

Cookie transport and CSRF controls are informed by the
[OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
and [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
The concrete lifetimes, schema, topology, and implementation slices above are
project design proposals, not requirements asserted by those references.
