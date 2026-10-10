# RestaurantOS engineering instructions

## Sources and scope

- Read applicable nested instructions; preserve `frontend/AGENTS.md` and follow
  its requirement to consult installed Next.js documentation before frontend code.
- Start with `README.md` and `docs/current-state.md`. Use accepted decisions in
  `docs/adr/`, architecture in `docs/architecture/`, endpoint contracts in
  `docs/api/`, and operational procedures in `docs/runbooks/`.
- `RestaurantOS_Master_Roadmap.md` defines milestone scope and exit criteria;
  `docs/milestone*/milestone-*-task.md` supplies issue acceptance criteria and
  dependencies.
  Plans include historical inspections and approvals: check current code and
  dated verification before treating them as current behavior or authorization.
  Report documentation/code disagreements; do not silently broaden permissions
  or implement a proposed roadmap feature as if it already existed.

## Architecture and ownership

- Keep the modular monolith (ADRs 0001/0002): one FastAPI API and PostgreSQL
  database, with a Next.js App Router frontend. Supported tooling is Python 3.12
  and Node 24; persistence uses async SQLAlchemy 2 and PostgreSQL 16. Frontend
  uses Next.js 16, React 19, strict TypeScript, and Tailwind 4.
- Business code belongs in `backend/app/modules/<feature>/`: HTTP routers and
  Pydantic schemas at the boundary, `service.py` for use cases/authorization,
  `domain/` for pure commands/rules/calculations, `repo/` for SQLAlchemy models
  and queries. Dependency direction is router -> service -> domain/repository.
  Domain code must not import HTTP or persistence frameworks; repositories have
  no HTTP responsibilities and never commit or roll back.
- Services own explicit write transactions (`async with session.begin()`).
  `app/db/database.py` owns session lifetime and teardown rollback. Principal
  lookup uses its own short-lived session; do not make authentication reads
  implicitly begin a transaction on the business command's session.
- Shared settings/logging/errors live in `app/core/`, HTTP middleware/error
  adapters in `app/http/`, and Base/session infrastructure in `app/db/`.
  Reuse `app/db/base.py`; `app/db/models/` contains compatibility re-exports,
  not the home for new business ORM declarations. Add layers only as needed;
  do not introduce generic base repositories or extra service directories.
- Follow ADR 0002's public service/domain interfaces for new cross-feature
  collaboration; keep relational joins in repositories. Existing order services
  reach into other features' persistence: this is not a pattern to expand or
  grounds for an unrelated architectural rewrite.
- Frontend routes/layouts live in `frontend/app/`, shared UI in `components/`,
  feature UI in `features/`, API transports/helpers in `lib/api/`, and contracts
  in `types/`. Reuse browser `lib/api/client.ts` and server `lib/api/server.ts`.
  Preserve existing URLs/error contracts: route prefixes are mixed and unversioned;
  roadmap `/api/v1` paths require a coordinated change, not opportunistic renaming.

## Security and business invariants

- Reuse auth's immutable principal and tenancy's access/policy interface. Resolve
  active membership and assignments on each operation; scope direct/nested IDs,
  lists, counts, and analytics. Never trust a supplied organization ID as access
  authority. Foreign/unassigned resources return 404; forbidden capabilities 403.
  Owners cover their organization; Managers/Employees require branch assignments.
  Employee permissions are kitchen preparation permissions, not cashier rights.
  See `docs/api/tenancy.md` and `docs/architecture/tenancy-schema.md`.
- Preserve authorization locks and same-transaction audit facts on writes. Audit
  failure must roll back business changes; audit reads are Owner-only and scoped.
- Follow ADR 0003 for cookie sessions: no tokens in JavaScript storage or response
  JSON; credentialed requests, exact trusted origins, and unsafe-request CSRF
  headers. SSR forwards only the access cookie and sends 401s through browser
  renewal; server components do not rotate cookies. Preserve serialized, bounded
  renewal and do not automatically replay refresh after transport failure.
- Backend prices/totals are authoritative; retain fixed-precision money and
  immutable order item name/price/total snapshots. Preserve lifecycle rules and
  draft-only item edits; payment status is not an external payment integration.
- Stock is consumed atomically on acceptance, never reserved by drafts and never
  returned on cancellation. Preserve the shared restaurant lock, order lock,
  ascending ingredient lock order, ledger/balance/audit atomicity, and idempotent
  replay/mismatch behavior. Reuse keys after uncertain failures. Details belong
  in `docs/api/orders.md`, `inventory.md`, and `recipes.md`.

## Database and local development

- Schema changes use new Alembic revisions in `backend/alembic/versions/`; review
  generated SQL, constraints, data preservation, and downgrade behavior. Maintain
  one migration head and register all models in Alembic's shared metadata imports.
  Run Alembic from `backend/`; `alembic/env.py` overrides the ini URL with typed
  settings from `DATABASE_URL`.
- Verify clean and seeded legacy upgrades plus `alembic check` using the
  disposable `migrations` gate. Preserve untracked legacy menu items, unprocessed
  legacy orders, and guards against discarding stock/replay history. Follow
  `docs/testing/migrations.md` when changing the representative baseline.
- Validation must never migrate the application database. Application migrations
  are an explicit operation; inspect its actual revision and use the appropriate
  runbook/backup procedure before a destructive change. Repository head and a
  recorded local database revision are not interchangeable.
- Developer `docker-compose.yml` runs PostgreSQL, host 5433/container 5432,
  retaining `postgres_data`. Optional Redis uses loopback port 6379 without
  persistence. API/frontend normally run on the host at 8000/3000.
  Use `localhost` consistently for both so host-only cookies reach SSR. Normal
  shutdown is `docker compose down`; do not delete the developer volume.
- Copy the tracked env examples to ignored local files and use
  `scripts/init-auth-env.py` for required independent auth secrets. Accounts are
  CLI-provisioned and need organization membership; follow auth/tenancy runbooks
  for provisioning/bootstrap. Compose credentials are local defaults only.
- `docker-compose.test.yml` supplies disposable PostgreSQL/Redis with unique
  project names and random ports. Redis currently validates infrastructure;
  application rate limits remain PostgreSQL-backed. Caching belongs to Milestone
  7; workers/events to Milestone 8. Do not add speculative infrastructure.
- `backend/Dockerfile` is a nonroot runtime image using locked dependencies and
  runtime-supplied configuration; startup does not migrate. There is no frontend
  Dockerfile or deployed environment. `/health` is liveness, not DB readiness.
- Install committed locks: Python `pip install --require-hashes -r
  backend/requirements-dev.txt`, frontend `npm ci`. Dependency changes update
  source `.in` files and generated locks together using
  `docs/testing/dependencies.md`; validation must not resolve new versions.

## Tests, CI, and completion

- Use `docs/testing/README.md` for commands and regression maps. From the root,
  `./scripts/validate.ps1` runs full Windows validation; Linux/macOS use
  `backend/.venv/bin/python scripts/validate.py`. Partial checks use
  `-Gate <name> -NoInstall` or `--gate <name> --no-install` with the test interpreter.
- Backend behavior: run `backend-unit` and `backend-integration` plus
  `backend-static` (Ruff lint/format, mypy). Pure tests are explicitly selected
  under `backend/tests/unit/` and require no services/secrets/network. All other
  selections, including characterization and top-level health/flow tests, are
  service-backed. Use real migrated PostgreSQL, not SQLite or mocked authorization.
  Fixtures truncate before/after tests and require an explicit
  `postgresql+asyncpg` `TEST_DATABASE_URL` ending in `_test`; retain these guards
  and prefer the disposable runner over manual database setup.
- Frontend behavior: run `frontend-tests` (Vitest component/client suites) and
  `frontend-static` (ESLint, Prettier, TypeScript); use `frontend-build` for build
  verification. `npm test` from `frontend/` runs fast tests without services.
  Use the `browser` gate for SSR, auth, permissions, and full workflows: Chromium
  exercises the real API and a production frontend in isolated copies/ports.
  Keep auth traces disabled because they contain cookies/passwords.
- Schema changes also require `migrations`; image changes require `image`.
  Add regressions at the affected layer for critical failure/isolation paths;
  concurrency tests must prove overlap at locks, not rely on sleeps. Coverage
  guides missing behavior, without a blanket percentage or duplicate count tests.
- CI in `.github/workflows/ci.yml` runs ten shared gates and aggregates them as
  `Milestone 6 acceptance`. Preserve that required check name and complete gate
  enforcement; policy changes require re-verification per
  `docs/testing/enforcement.md`. `frontend`'s `npm run validate` alone is not the
  full repository gate.
- For issue/milestone work, inspect git status, existing implementation, schema,
  issue criteria and dependencies first; state the scope/files and migration risks.
  Complete small vertical slices, preserve user changes, and avoid unrelated
  moves, refactors, dependency upgrades, or repository-wide formatting.
- Before completion, run relevant tests/static/build/migration gates and report
  exact commands, outcomes, omissions, schema/API changes, and remaining risks.
  Milestone acceptance requires the full gate set and demonstrated exit criteria;
  skip/partial runs and historical pass counts do not establish completion.
  Update relevant API/setup/current-state/roadmap evidence within the authorized
  scope. Never invent results or mark unverified criteria complete. Historical
  plan approvals do not authorize commits, pushes, or publication for a new task.
