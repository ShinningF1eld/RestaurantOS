# RestaurantOS current state

Last verification: 2026-10-02 for Milestone 4, including PostgreSQL acceptance
and live cutover. Historical Milestone 3/schema results are dated below.

Milestone 4 schema/model expansion was verified separately on 2026-10-01.
The new migration was tested in disposable databases only; the application
database was not migrated by that work. See the Milestone 4 section below.

This document describes the repository as it exists. It is not a statement that
roadmap features are complete.

## Repository and runtime baseline

- Backend: FastAPI 0.141.1, SQLAlchemy 2.0.52 async sessions, Alembic 1.19.1.
- Frontend: Next.js 16.3.7, React 19.2.8, TypeScript, and Tailwind CSS 4.
- Database: PostgreSQL 16 in Docker Compose, host port `5433` to container port
  `5432`, with the named volume `postgres_data`.
- Supported baseline: Python 3.12 in documentation and CI; Node.js 24 in CI.
- Audit host: Python 3.13.15, Node.js 24.14.1, npm 11.11.0.
- The only repository instruction file is `frontend/AGENTS.md`.

Docker Compose currently manages only PostgreSQL. The API and frontend run as
host processes. Compose credentials are predictable local-development defaults
and are not suitable for shared or deployed environments.

## Configuration

| Component | Variable | Example file |
|---|---|---|
| Backend and Alembic | `DATABASE_URL` | `backend/.env.example` |
| Backend runtime | `ENVIRONMENT`, `LOG_LEVEL`, `DATABASE_ECHO` | `backend/.env.example` |
| Authentication | Required independent `AUTH_JWT_SECRET`, `AUTH_RATE_LIMIT_SECRET`; trusted origins, cookie security, lifetimes and limits | `backend/.env.example` | <!-- pragma: allowlist secret -->
| Backend tests | `TEST_DATABASE_URL` (database name must end in `_test`) | `backend/.env.example` |
| Frontend | `NEXT_PUBLIC_API_URL`, server-only `API_URL` | `frontend/.env.example` |

Both real local environment files are ignored. The example files contain no
real credentials and remain commit-trackable.

## Database schema and migrations

The current models and tables are:

| Entity | Primary key | Important relationships/fields |
|---|---|---|
| Restaurant | `id` | Belongs to exactly one organization; has menus and orders |
| Menu | `menu_id` | Belongs to a restaurant; has menu items |
| MenuItem | `menu_item_id` | Belongs to a menu; numeric price; availability flag |
| Order | `order_id` | Belongs to a restaurant; controlled lifecycle and payment status; subtotal/total |
| OrderItem | `order_item_id` | Belongs to an order; nullable catalog reference plus immutable name, price, and line-total snapshots |
| User | UUID `id` | Normalized unique email, Argon2id hash, active/disabled status |
| AuthSession | UUID `id` | User, absolute expiry, family revocation |
| RefreshToken | UUID `id` | Token digest, family, consumed history and successor |
| RateLimitBucket | Key digest + window start | Atomic shared counters and expiry |
| Organization | UUID `id` | Unique generated display number and slug; active/archived status |
| Membership | UUID `id` | Unique user; one organization; OWNER/MANAGER/EMPLOYEE; active/revoked |
| RestaurantAssignment | `membership_id` + `restaurant_id` | Membership and restaurant must belong to the same organization |
| AuditEntry | UUID `id` | Organization-scoped safe mutation facts; Owner-only inspection |

Alembic has one linear chain:

```text
9007636220c5 -> 694f7189fe51 -> 2d7747d9f5b1 -> 4a1e9a2dc8e4 -> 72bd03a1f901 -> 83c7e1b4a902 -> 94d8f2c5b013 (head; live database verified)
```

At Milestone 3, the existing local database was verified at its head and `alembic check` reported
no model drift. A separately named empty local database was upgraded through all
five revisions to head, checked for drift, and removed. CI also performs the
zero-to-head upgrade against a clean PostgreSQL service before integration tests.

Known deferred data-model work includes explicit currency and restaurant
timezone fields, database-level status constraints, and broader restaurant/menu
deletion policies. Milestone 1 preserves ordered-item history and centralizes
status transitions in the application.

## Backend endpoint inventory

There are 29 protected business endpoints, four authentication endpoints and
three utility endpoints. `/api/test-db` requires authentication and returns 404
in production. Public health/probe responses and API docs contain no business data.

| Area | Methods and paths |
|---|---|
| Restaurants | `POST/GET /api/restaurants`; `GET/PUT/DELETE /api/restaurants/{restaurant_id}` |
| Menus | `POST/GET /restaurants/{restaurant_id}/menus`; `GET/PUT/DELETE /menus/{menu_id}` |
| Menu items | `POST/GET /menus/{menu_id}/items`; `GET/PUT/DELETE /menu-items/{menu_item_id}` |
| Orders | `POST/GET /api/restaurants/{restaurant_id}/orders`; `GET/PUT/DELETE /api/orders/{order_id}` |
| Analytics | `GET /api/restaurants/{restaurant_id}/analytics/dashboard` |
| Tenancy | `GET /api/access`; `POST /api/organizations`; `GET /api/organization`; `GET/POST /api/memberships`; `PUT/DELETE /api/memberships/{membership_id}` |
| Audit | `GET /api/audit` |
| Authentication | `POST /auth/login`; `POST /auth/refresh`; `POST /auth/logout`; `GET /auth/me` |
| Utility | `GET /health`; `GET /api/test`; `GET /api/test-db` |

The current prefixes are intentionally documented, not endorsed: menu routes
are unprefixed while other business routes use `/api`, and no route uses the
roadmap's target `/api/v1` convention.

## Frontend route inventory

- `/`
- `/login`
- `/session/renew`
- `/dashboard/restaurants`
- `/restaurants/[restaurant_id]/dashboard`
- `/restaurants/[restaurant_id]/orders`
- `/restaurants/[restaurant_id]/menu`
- `/restaurants/[restaurant_id]/menu/[menu_id]`
- `/restaurants/[restaurant_id]/inventory`
- `/restaurants/[restaurant_id]/employees`

Restaurant CRUD, menu CRUD, menu-item CRUD, multi-item order entry, paginated
order listing/status actions, and dashboard metrics are present. The restaurant
workspace has route-level `loading.tsx`, `error.tsx`, and `not-found.tsx`
boundaries. Inventory remains mock UI for later milestones. Staff access uses the real
Owner membership administration API. Controls/navigation reflect capabilities.

The shared restaurant navigation still links to nonexistent `tables` and
`settings` routes, and the root page shows hardcoded operational figures. These
are later product gaps; the restaurant workspace itself now surfaces not-found
and API failures instead of substituting mock data.

## Core request flows

### Catalog management

The browser usually uses small modules under `frontend/lib/api` and
`NEXT_PUBLIC_API_URL` to call FastAPI through the shared credentialed browser
transport. Server-rendered pages use a separate server-only transport forwarding
only the access cookie. The root-page connectivity probe is an
exception: it hardcodes `http://localhost:8000/api/test`. Router handlers
translate HTTP schemas into typed commands and delegate to restaurant/catalog
application services. Services own explicit transaction contexts and focused
repositories contain the SQLAlchemy queries without committing.

Frontend contracts are handwritten and have verified drift: Restaurant address
and phone are non-null strings and response timestamps are omitted in the
frontend type, while the backend permits nulls and returns timestamps. Menu-item
price is a JavaScript `number` in the frontend but a Pydantic `Decimal` in the
backend.

### Order creation

The backend accepts one or more menu-item IDs and quantities, scopes menu items
to the restaurant, rejects unavailable items, reads prices from PostgreSQL,
calculates totals, snapshots item names/prices, and commits the order and items
together. Framework-independent domain functions control lifecycle and payment
rules, while the order service owns the transaction and repositories own
explicit persistence queries. Orders carry a basic payment status, and
restaurant order lists are paginated. The
frontend exposes order entry and sequential kitchen/status actions.

### Analytics

The dashboard endpoint counts only orders whose status is `COMPLETED`.
It returns daily sales/orders, average order value, a seven-day graph, and top
items. Calculations currently use host-local dates and order creation time,
rather than restaurant timezone and completion time. The router delegates to a
typed analytics service and focused read repository.

### Session, errors, and logging

The request dependency owns async-session lifetime and defensively rolls back
unfinished work. Write services own successful transaction boundaries;
repositories never commit or roll back. Domain/application failures use typed
exceptions mapped by one HTTP adapter while preserving the existing
`{"detail": ...}` response contract. Structured JSON logging includes request
method, path, status, duration, and the validated/generated request ID returned
in `X-Request-ID`.

## Quality baseline

The repository now defines these local and CI gates:

```text
docker compose config --quiet
python -m pip check
detect-secrets-hook --baseline .secrets.baseline <repository files>
python -m ruff check app tests
python -m mypy app
python -m pytest
python -m alembic upgrade head       # clean CI database
python -m alembic check
npm run lint
npm run typecheck
npm run build
python scripts/run-browser-tests.py # from root, with built frontend and isolated DB
```

Mypy now checks the full backend application. Important core, domain,
repository, schema, service, and HTTP-adapter modules additionally disallow
untyped function definitions.

### Historical reproduced results (Milestones 0–2, 2026-09-16)

| Command/check | Reproduced result |
|---|---|
| `./scripts/validate.ps1` | Passed locally on Windows, including every configured local gate |
| `docker compose config --quiet` | Passed |
| `python -m pip check` | Passed; no broken requirements |
| `detect-secrets-hook --baseline .secrets.baseline ...` | Passed over tracked and untracked candidate files; two Alembic revision IDs are audited false positives |
| `python -m ruff check app tests` | Passed |
| `python -m mypy app` | Passed; 41 source files |
| `python -m pytest` | Passed; 56 tests including domain, service, transaction, characterization, analytics, and the Milestone 1 critical flow |
| Existing DB `alembic current` and `alembic check` | Passed at `4a1e9a2dc8e4 (head)` with no model drift |
| Empty temporary DB `alembic upgrade head`, `current`, and `check` | Passed through all four revisions; temporary database removed afterward |
| `npm run lint` | Passed |
| `npm run typecheck` | Passed after Next.js route type generation |
| `npm run build` | Passed; production build generated all current routes |
| GitHub Actions workflow | Passed after the Milestone 0 baseline commit |

Milestone 0 is complete: setup and validation are documented, local validation
passes, tracked files pass secret scanning, the schema and endpoint inventory is
recorded, and GitHub Actions reproduced the checks with clean service state.

## Milestone 1 completion evidence

Milestone 1 is complete. The PostgreSQL integration flow creates restaurants,
menus and items, rejects cross-restaurant and unavailable items, proves that
client-supplied prices do not affect totals, verifies lifecycle transitions and
payment status, completes a sale, preserves history after catalog deactivation,
and verifies completed-only dashboard revenue and top items. The same test
confirms cancelled tickets do not contribute revenue.

Local validation passed Ruff, full-app mypy, PostgreSQL-backed pytest, Alembic
upgrade/drift checks, secret scanning, ESLint, TypeScript, and the Next.js
production build. A separately named empty PostgreSQL database was migrated
from zero through `4a1e9a2dc8e4` and removed after verification. OpenAPI was
inspected for the order create request, paginated response, payment status, and
nullable historical catalog reference.

At Milestone 1 completion, authentication, multi-tenancy, inventory, events, currency/timezone modeling,
and production payment integration are
intentionally deferred to later milestones.

That historical Milestone 1 workflow was an unauthenticated local-development
flow. Milestone 3 added authentication; Milestone 4 now enforces tenant isolation
and RBAC. Inventory, events and provider integration remain future work.

## Milestone 2 completion evidence

Milestone 2 is complete. Restaurant, menu, menu-item, order, and analytics
routers now delegate to typed application services and focused repositories.
Order lifecycle/payment rules are framework-independent and directly unit
tested. All critical writes use explicit service-owned transactions, and
database-backed tests verify rollback of a partially applied order update.

Typed settings are shared by the API and Alembic. SQL echo is configurable and
off by default. Domain errors have centralized HTTP mapping, and structured
request logs carry the same request ID returned to clients. ORM declarations
use SQLAlchemy 2 typed mappings while API schemas remain separate.

The isolated PostgreSQL test harness refuses database names without a `_test`
suffix. The final lead review passed Ruff, full-app mypy, 56 backend tests,
Alembic drift detection, frontend ESLint and TypeScript, and the Next.js
production build. No schema migration or public API route/schema change was
introduced.

## Milestone 3 completion evidence

Milestone 3 is complete locally on 2026-09-30. Two GPT-6.1 Sol agents at medium
reasoning implemented backend and test work; the lead integrated the frontend,
reviewed the code, corrected findings, and ran the combined verification.

Authentication is the first feature-first module under `app/modules/auth`.
The service/domain/repository responsibilities from Milestone 2 remain intact.
Legacy catalog, order and analytics folders are intentionally unchanged.

| Roadmap exit criterion | Verified evidence |
|---|---|
| Protected routes require authentication | Real HTTP tests enumerate all business operations and reject anonymous access; authenticated catalog/order transaction and sale regressions pass. |
| Browser refresh preserves a valid session safely | Chromium verifies reload, expired-access SSR deep-link renewal, one rotation across concurrent tabs, HttpOnly cookies and absence of tokens from browser storage/HTML. |
| Happy path and abuse cases covered | Generic login failures, disabled users, JWT claim/signature/expiry checks, refresh replay committing family revocation, rotation/logout/disable races, atomic rollback, CSRF/CORS, rate limits and storage-outage failures pass. |

Reproduced validation (Windows; Python 3.13.15, Node 24; CI targets Python 3.12):

| Command | Result |
|---|---|
| `npm run build` in frontend | Passed on patched Next.js 16.3.7 |
| `./scripts/validate.ps1 -SkipBuild` from root, immediately after the current build | Passed all remaining gates, including Compose, pip check, candidate-file secret scan, Ruff, mypy (60 sources), application/test DB migrations, model drift, pytest, ESLint, TypeScript and real browser tests |
| Backend pytest in that validation | 147 passed; 57 existing deprecation warnings |
| Browser suite via `scripts/run-browser-tests.py` in that validation | 12 passed against real FastAPI/PostgreSQL and production Next.js with Chromium |
| `python scripts/check-auth-migration.py` using the backend venv and `TEST_DATABASE_URL` | Clean-to-head and previous-head upgrade passed; auth downgrade/re-upgrade on disposable data preserved restaurant/order/name/price history; no model drift |
| `npm audit fix` after patch dependency updates | Reported zero known vulnerabilities |

The full validation uses an explicit isolated `TEST_DATABASE_URL` ending in
`_test`. Browser runs fail clearly if ports are occupied or database setup is
unavailable. Temporary migration databases were dropped after verification.
The existing application DB was upgraded additively to `72bd03a1f901`; its
restaurant/order data was not rewritten. Local secrets were initialized in the
ignored `.env` without printing or replacing existing values. No default account
was created: operators provision their own password using the documented CLI.

Lead review fixed an access-expiry response clearing the usable refresh cookie,
a redundant migration constraint that caused model drift, per-call password
limiter allocation, malformed JWT claim handling, and credential-bearing CLI
validation errors. Browser verification additionally prevented repeated automatic
refresh after a failed/ambiguous rotation. Tests exercise real auth dependencies;
there is no production bypass flag.

Remaining boundaries and limitations:

- At Milestone 3 completion, provisioned accounts shared the workspace. Milestone 4
  now enforces organization authorization and roles; public registration remains
  unimplemented.
- Production requires a same-host HTTPS frontend/API gateway; hosting/deployment
  has not been implemented or verified. Local Chromium is verified, other browser
  engines are not. Browsers without Web Locks require re-login at expiry.
- A lost refresh response can require re-login. Fixed-window auth limits can
  burst at a boundary; Redis migration and measured tuning remain future work.
- Existing naive-UTC ORM timestamp and Starlette TestClient deprecations remain.
  A cancelled Next.js streamed navigation logged a destination-stream-close
  diagnostic during browser testing; all browser assertions passed.
- GitHub Actions definitions include a separate real-browser job, but were not
  executed remotely because this work is intentionally not pushed.

See [authentication operations](runbooks/authentication.md),
[API contract](api/authentication.md), [feature module ADR](adr/0002-feature-modules.md)
and [session ADR](adr/0003-authentication-sessions.md).

## Milestone 4 completion evidence

The schema-only slice adds Organization, Membership, RestaurantAssignment and
AuditEntry models in new tenancy/audit feature modules, using the shared Base.
Revision `83c7e1b4a902` extends `72bd03a1f901`, adds the nullable restaurant
organization FK, and backfills legacy restaurants into a named development
organization. Composite FKs reject cross-organization assignments and audit
restaurant links. Membership roles are exactly OWNER, MANAGER and EMPLOYEE;
EMPLOYEE receives the planned kitchen permissions in the completed slice below.

Verified on 2026-10-01: Ruff and full-backend mypy (68 sources), 163 PostgreSQL
backend tests including 16 new schema tests, clean/previous-head migration
upgrades, no model drift, and downgrade/re-upgrade preserving historical orders
and users. Checks ran against newly created disposable databases, which were
removed afterward. No application database upgrade or commit was performed.

Implemented on 2026-10-02: one-organization-per-user uniqueness, non-null
restaurant tenant scope, organization display numbers (development workspace 1),
explicit idempotent legacy Owner bootstrap and authenticated first-Owner creation,
Owner staff administration, fresh membership/assignment checks, centralized
capabilities, scoped repositories and transactional allowlisted audits. Business
implementations now reside in corresponding feature modules. The unused top-level
domain/repository/service/router/schema compatibility folders have been removed.
Role-aware screens include Owner staff administration and Employee
preparation controls without financial/menu/staff mutation controls.

Verified on 2026-10-02 after PostgreSQL recovered:

- All 231 backend tests passed, including 104 database-free unit tests and
  PostgreSQL integration coverage for isolation, assignments, revocation, role
  changes, last-Owner protection, bootstrap and transactional audit rollback.
- All 13 Chromium tests passed against a separate disposable database, including
  real kitchen controls and direct forbidden/mixed writes. Browser findings fixed
  outage messaging and a session-renewal broadcast that reloaded the page during
  a retried write. Renewal now preserves the page; login/logout still coordinate
  identity changes across tabs. The regression asserts one retry and no reload.
- Clean and previous-head migration rehearsals passed with no model drift,
  preserved users/order snapshots, idempotent bootstrap and disposable
  downgrade/re-upgrade. The checker removed its temporary databases.
- Ruff, full-app mypy (98 sources), frontend ESLint, TypeScript and the production
  build passed. Candidate repository files passed secret scanning.
- The live database was backed up, the backup restored and fingerprint-verified
  in a disposable database, and the live database migrated to `94d8f2c5b013`
  with no model drift. Restaurant 1 belongs to organization 1 and the sole
  existing user has an active OWNER membership. Bootstrap ran twice with exactly
  one membership and one bootstrap audit entry. All original account, catalog,
  order and item data was preserved except the new restaurant organization link.
  Restore/browser databases created for verification were removed; the backup
  remains in the ignored `.local-backups` folder.

Milestone 4's exit criteria are verified locally: every business endpoint has an
explicit policy, cross-tenant integration tests cover reads/writes/nested IDs/list
endpoints, and sensitive mutation audits contain safe facts without secrets.
Remote CI was not run. See [role/API policies](api/tenancy.md),
[schema](architecture/tenancy-schema.md) and [cutover runbook](runbooks/tenancy.md).
