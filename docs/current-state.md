# RestaurantOS current state

Last verified: 2026-09-16 after Milestone 1 completion.

This document describes the repository as it exists. It is not a statement that
roadmap features are complete.

## Repository and runtime baseline

- Backend: FastAPI 0.141.1, SQLAlchemy 2.0.52 async sessions, Alembic 1.19.1.
- Frontend: Next.js 16.3.1, React 19.2.8, TypeScript, and Tailwind CSS 4.
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
| Frontend | `NEXT_PUBLIC_API_URL` | `frontend/.env.example` |

Both real local environment files are ignored. The example files contain no
real credentials and remain commit-trackable.

## Database schema and migrations

The current models and tables are:

| Entity | Primary key | Important relationships/fields |
|---|---|---|
| Restaurant | `id` | Has menus and orders |
| Menu | `menu_id` | Belongs to a restaurant; has menu items |
| MenuItem | `menu_item_id` | Belongs to a menu; numeric price; availability flag |
| Order | `order_id` | Belongs to a restaurant; controlled lifecycle and payment status; subtotal/total |
| OrderItem | `order_item_id` | Belongs to an order; nullable catalog reference plus immutable name, price, and line-total snapshots |

Alembic has one linear chain:

```text
9007636220c5 -> 694f7189fe51 -> 2d7747d9f5b1 -> 4a1e9a2dc8e4 (head)
```

The existing local database was verified at head and `alembic check` reported
no model drift. A separately named empty local database was upgraded through all
four revisions to head, checked for drift, and removed. CI also performs the
zero-to-head upgrade against a clean PostgreSQL service before integration tests.

Known deferred data-model work includes explicit currency and restaurant
timezone fields, database-level status constraints, and broader restaurant/menu
deletion policies. Milestone 1 preserves ordered-item history and centralizes
status transitions in the application.

## Backend endpoint inventory

There are 21 business endpoints plus three utility endpoints.

| Area | Methods and paths |
|---|---|
| Restaurants | `POST/GET /api/restaurants`; `GET/PUT/DELETE /api/restaurants/{restaurant_id}` |
| Menus | `POST/GET /restaurants/{restaurant_id}/menus`; `GET/PUT/DELETE /menus/{menu_id}` |
| Menu items | `POST/GET /menus/{menu_id}/items`; `GET/PUT/DELETE /menu-items/{menu_item_id}` |
| Orders | `POST/GET /api/restaurants/{restaurant_id}/orders`; `GET/PUT/DELETE /api/orders/{order_id}` |
| Analytics | `GET /api/restaurants/{restaurant_id}/analytics/dashboard` |
| Utility | `GET /health`; `GET /api/test`; `GET /api/test-db` |

The current prefixes are intentionally documented, not endorsed: menu routes
are unprefixed while other business routes use `/api`, and no route uses the
roadmap's target `/api/v1` convention.

## Frontend route inventory

- `/`
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
boundaries. Inventory and employees remain mock UI for later milestones.

The shared restaurant navigation still links to nonexistent `tables` and
`settings` routes, and the root page shows hardcoded operational figures. These
are later product gaps; the restaurant workspace itself now surfaces not-found
and API failures instead of substituting mock data.

## Core request flows

### Catalog management

The browser usually uses small modules under `frontend/lib/api` and
`NEXT_PUBLIC_API_URL` to call FastAPI. The root-page connectivity probe is an
exception: it hardcodes `http://localhost:8000/api/test`. Router handlers
validate parent records and commit directly through one async SQLAlchemy
session. There is no separate application-service layer yet.

Frontend contracts are handwritten and have verified drift: Restaurant address
and phone are non-null strings and response timestamps are omitted in the
frontend type, while the backend permits nulls and returns timestamps. Menu-item
price is a JavaScript `number` in the frontend but a Pydantic `Decimal` in the
backend.

### Order creation

The backend accepts one or more menu-item IDs and quantities, scopes menu items
to the restaurant, rejects unavailable items, reads prices from PostgreSQL,
calculates totals, snapshots item names/prices, and commits the order and items
together. A centralized state machine controls lifecycle transitions, orders
carry a basic payment status, and restaurant order lists are paginated. The
frontend exposes order entry and sequential kitchen/status actions.

### Analytics

The dashboard endpoint counts only orders whose status is `COMPLETED`.
It returns daily sales/orders, average order value, a seven-day graph, and top
items. Calculations currently use host-local dates and order creation time,
rather than restaurant timezone and completion time.

## Quality baseline

The repository now defines these local and CI gates:

```text
docker compose config --quiet
python -m pip check
detect-secrets-hook --baseline .secrets.baseline <repository files>
python -m ruff check app tests
python -m mypy app/schemas
python -m pytest
python -m alembic upgrade head       # clean CI database
python -m alembic check
npm run lint
npm run typecheck
npm run build
```

Mypy intentionally starts with `app/schemas`, the most consistently typed
backend boundary. The full `app` baseline is run during Milestone 0 validation
and recorded below, but is not made a required gate through broad suppressions.

### Reproduced results

| Command/check | Reproduced result |
|---|---|
| `./scripts/validate.ps1` | Passed locally on Windows, including every configured local gate |
| `docker compose config --quiet` | Passed |
| `python -m pip check` | Passed; no broken requirements |
| `detect-secrets-hook --baseline .secrets.baseline ...` | Passed over tracked and untracked candidate files; two Alembic revision IDs are audited false positives |
| `python -m ruff check app tests` | Passed |
| `python -m mypy app/schemas` | Passed; 5 source files |
| `python -m mypy app` | Baseline failed with 12 SQLAlchemy typing errors across `routers/order.py`, `routers/menu_item.py`, and `routers/menu.py`; not a required gate yet |
| `python -m pytest` | Passed; 2 tests including the PostgreSQL-backed critical restaurant-to-dashboard flow |
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

Local validation passed Ruff, schema mypy, PostgreSQL-backed pytest, Alembic
upgrade/drift checks, secret scanning, ESLint, TypeScript, and the Next.js
production build. A separately named empty PostgreSQL database was migrated
from zero through `4a1e9a2dc8e4` and removed after verification. OpenAPI was
inspected for the order create request, paginated response, payment status, and
nullable historical catalog reference.

Authentication, multi-tenancy, inventory, events, broader application-service
boundaries, currency/timezone modeling, and production payment integration are
intentionally deferred to later milestones.

The Milestone 1 workflow therefore remains an unauthenticated local-development
flow. It does not claim tenant isolation or production authorization; those
security boundaries are explicit requirements of Milestones 3 and 4.
