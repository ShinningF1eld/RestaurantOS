# RestaurantOS Intelligence — Master Engineering Roadmap

> A production-oriented, multi-tenant restaurant operations and intelligence platform built to demonstrate strong software engineering, backend architecture, data engineering, ML, and applied AI skills.

## 0. How to use this document

This roadmap is both:

1. A product and engineering plan for RestaurantOS.
2. An execution brief for an AI coding agent working inside the existing repository.

Do **not** attempt to implement the entire roadmap in one pull request or one Codex session. Work milestone by milestone. At the start of every milestone:

1. Inspect the repository and current database schema.
2. Read existing project instructions, including every applicable `AGENTS.md`.
3. Report what already exists, what is incomplete, and what will change.
4. Propose a small implementation plan and identify risky migrations.
5. Preserve working behavior and unrelated user changes.
6. Implement one vertical slice at a time.
7. Run tests, linters, type checks, and migrations before declaring completion.
8. Update this roadmap, the README, and API documentation when reality differs from the assumptions below.

The coding agent must never invent benchmark numbers, ML metrics, scale claims, or completed features. Only publish measurements that were actually reproduced.

---

## 1. Project vision

RestaurantOS should become an operating platform for small and medium restaurants. It should support day-to-day restaurant workflows and use the resulting operational data to produce forecasts, alerts, and evidence-backed management insights.

The finished portfolio project should demonstrate:

- Product-oriented full-stack engineering.
- A well-structured FastAPI backend.
- Relational data modeling and safe schema migrations.
- Authentication, authorization, tenant isolation, and auditability.
- Transactional order and inventory workflows.
- Asynchronous jobs and reliable event processing.
- Automated testing and CI/CD.
- Caching, performance testing, and observability.
- Reproducible ML experiments and model deployment.
- A constrained tool-using AI analyst with citations and safety controls.
- Real cloud deployment and measurable engineering results.

### Product promise

> A restaurant owner can securely operate one or more branches, manage menus and staff, process orders, track inventory and sales, receive demand and anomaly alerts, and ask an AI analyst questions grounded in real operational data and restaurant documents.

### Primary users

| Persona | Main needs |
|---|---|
| Organization owner | Manage branches, staff, financial overview, policies, and billing-ready account boundaries |
| Restaurant manager | Manage menu, inventory, shifts, orders, reports, alerts, and forecasts |
| Employee/cashier | Create and update orders within restricted permissions |
| Kitchen staff | View accepted orders and update preparation status |
| Portfolio reviewer/interviewer | Understand architecture, trade-offs, tests, performance, ML evaluation, and deployment |

---

## 2. Current-state assumptions

The repository currently appears to contain:

- Next.js frontend with Tailwind CSS.
- FastAPI backend.
- PostgreSQL, likely running through Docker with host port `5433` mapped to container port `5432`.
- SQLAlchemy and Alembic, or work in progress toward them.
- CRUD/UI for restaurants, menus, and menu items.
- An order system or partial ordering flow.
- Early dashboard/analytics work.

These are assumptions, not facts. The first agent task is to audit the repository and replace this section with verified findings.

### Immediate definition of “core CRUD complete”

Do not build CRUD for every possible noun. The initial CRUD stage is complete when this vertical workflow works:

1. Create a restaurant.
2. Create a menu for it.
3. Add available menu items with prices.
4. Create an order containing one or more items.
5. Calculate authoritative prices on the server.
6. Move the order through valid statuses.
7. Complete or cancel the order.
8. Reflect completed sales in a basic dashboard.

Required core entities:

- Restaurant
- Menu
- Menu item
- Order
- Order item
- Payment record or payment status

Deferred until justified:

- Loyalty programs
- Reviews
- Coupons and advanced promotions
- Supplier marketplace
- Reservations
- Delivery routing
- Payroll
- Full accounting

---

## 3. Architecture strategy

### 3.1 Start as a modular monolith

Do not begin with independently deployed microservices. Use a modular monolith with clear boundaries:

```text
Next.js web application
          |
          v
FastAPI API (modular monolith)
  |-- identity and access
  |-- organizations and restaurants
  |-- catalog and menus
  |-- ordering and payments
  |-- inventory
  |-- analytics
  |-- forecasting and alerts
  |-- documents and AI analyst
          |
          +--> PostgreSQL + pgvector
          +--> Redis
          +--> Object storage
          +--> Background worker
```

The API and background worker may run as separate processes/containers while sharing domain code. Introduce a separate service only if at least one of these becomes true:

- It requires an independent scaling profile.
- It has a materially different availability or security boundary.
- Deployments repeatedly interfere with unrelated modules.
- The boundary is stable and backed by measured operational need.

### 3.2 Backend layering

Use this dependency direction:

```text
API router -> application service/use case -> repository/domain -> database or external adapter
```

Responsibilities:

| Layer | Responsibility |
|---|---|
| Router | HTTP parsing, dependency injection, status codes, response schemas |
| Application service | Use-case orchestration, authorization call, transaction boundary, business rules |
| Domain | State transitions, invariants, policies, value objects where useful |
| Repository | Persistence operations without HTTP knowledge |
| Infrastructure | SQLAlchemy, Redis, queue, email, object storage, LLM/model clients |

Avoid ceremony that does not create value. Simple reads can remain simple, but complex writes must not put all business logic directly inside route handlers.

### 3.3 Suggested repository structure

Adapt existing names rather than performing a blind rewrite.

```text
backend/
  app/
    api/
      dependencies/
      routers/
    core/
      config.py
      security.py
      logging.py
      errors.py
    db/
      base.py
      session.py
      migrations/
    modules/
      identity/
      organizations/
      catalog/
      orders/
      inventory/
      analytics/
      forecasting/
      documents/
      ai_analyst/
      audit/
    infrastructure/
      cache/
      events/
      object_storage/
      observability/
    workers/
    tests/
frontend/
  app/
  components/
  features/
  lib/
  types/
infra/
  docker/
  terraform/                 # later milestone
docs/
  adr/
  architecture/
  api/
  runbooks/
ml/
  data/
  features/
  training/
  evaluation/
  serving/
```

### 3.4 Engineering principles

- PostgreSQL is the system of record.
- Derive tenant scope from authenticated membership, not a trusted client-supplied organization ID.
- Server calculates totals; client totals are previews only.
- Monetary values use fixed precision or integer minor units, never binary floating point.
- Store timestamps in UTC and display in the restaurant's configured timezone.
- Every critical write has a transaction boundary.
- Events represent facts that already happened; commands request an action.
- External retries require idempotency.
- Prefer database constraints over application-only assumptions.
- Add complexity only after a working vertical slice and a measured need.
- Maintain backward-compatible APIs or document and version breaking changes.

---

## 4. Target data model

Exact names should follow existing conventions. Add indexes and constraints based on actual query patterns.

### 4.1 Identity and tenancy

| Entity | Important fields and rules |
|---|---|
| User | id, email normalized and unique, password_hash or external identity, status, created_at |
| Organization | id, name, slug, owner metadata, timestamps |
| Membership | user_id, organization_id, role, status; unique user/org pair |
| Restaurant | id, organization_id, name, timezone, currency, status; indexed by organization |
| Restaurant assignment | membership/user, restaurant, optional branch-level role; unique assignment |
| Refresh session | token family/session ID, user, hashed token identifier, expiry, revoked_at, metadata |
| Audit log | actor, org, restaurant, action, resource type/id, safe before/after summary, timestamp, request/trace ID |

Suggested initial roles:

- `OWNER`
- `MANAGER`
- `EMPLOYEE`
- `KITCHEN`

Implement permissions as named capabilities, not scattered role comparisons. Example capabilities:

- `restaurant.read`
- `restaurant.update`
- `staff.manage`
- `menu.manage`
- `order.create`
- `order.status.update`
- `analytics.read`
- `inventory.manage`
- `ai.query`

### 4.2 Catalog

| Entity | Important fields and rules |
|---|---|
| Menu | restaurant_id, name, active period/status |
| Menu item | menu_id, name, description, price, currency, availability, category, timestamps |
| Menu item price history | optional later; item, old/new price, effective timestamp |
| Modifier group/modifier | deferred until order flow is stable |

Important constraints:

- A menu item belongs to a menu that belongs to the same restaurant context.
- Deactivating an item must not destroy historical order data.
- Historical order items store a snapshot of name and unit price.

### 4.3 Ordering and payments

| Entity | Important fields and rules |
|---|---|
| Order | restaurant_id, public order number, status, subtotal, tax, discount, total, currency, version, timestamps |
| Order item | order_id, menu_item_id nullable for preserved history, item-name snapshot, unit-price snapshot, quantity, line total |
| Payment | order_id, status, amount, method, provider reference, idempotency key, timestamps |
| Idempotency record | tenant/user scope, key, request hash, response/status, expiry |

Suggested order state machine:

```text
DRAFT -> SUBMITTED -> ACCEPTED -> PREPARING -> READY -> COMPLETED
   |          |           |           |
   +----------+-----------+-----------+-> CANCELLED
```

Valid transitions must be centralized and tested. Completed and cancelled orders are terminal unless an explicit compensating/refund workflow is later added.

### 4.4 Inventory

Use a ledger instead of only mutating a single stock number.

| Entity | Important fields and rules |
|---|---|
| Ingredient | restaurant_id, name, unit, reorder threshold, active |
| Recipe component | menu_item_id, ingredient_id, quantity required, wastage factor if needed |
| Inventory movement | ingredient_id, quantity delta, movement type, order/reference ID, actor, timestamp |
| Inventory balance | ingredient_id, current quantity, version; derived/cacheable but transactionally maintained initially |

Movement types may include `PURCHASE`, `ORDER_CONSUMPTION`, `ADJUSTMENT`, `WASTE`, `REVERSAL`.

### 4.5 Events and outbox

| Entity | Important fields and rules |
|---|---|
| Outbox event | event_id UUID, aggregate type/id, event type/version, tenant scope, payload, occurred_at, published_at, attempts |
| Consumer receipt/inbox | consumer name + event_id unique, processed_at, result/error metadata |

The domain write and outbox insertion must commit in the same PostgreSQL transaction.

---

## 5. API conventions

Use the existing API style where sound; otherwise converge gradually on these conventions.

### 5.1 Versioning and resource paths

- Prefix public API routes with `/api/v1`.
- Prefer nested routes when ownership is essential, for example `/restaurants/{restaurant_id}/menus`.
- Use authenticated context and authorization checks even when a restaurant ID appears in a URL.
- Paginate list endpoints.
- Add filtering/sorting only for actual UI/query needs.
- Publish OpenAPI documentation and representative examples.

### 5.2 Errors

Return a consistent error envelope:

```json
{
  "error": {
    "code": "ORDER_INVALID_TRANSITION",
    "message": "Order cannot move from COMPLETED to PREPARING.",
    "details": {},
    "request_id": "..."
  }
}
```

Never expose stack traces, SQL, secrets, password hashes, raw model prompts, or internal provider responses to clients.

### 5.3 Idempotency and concurrency

- Require `Idempotency-Key` for payment-like operations and consider it for order submission.
- Hash or canonicalize relevant request content to reject reuse with a different payload.
- Use optimistic versioning or row locks where concurrent updates can violate invariants.
- Return `409 Conflict` for detected write conflicts or invalid concurrent state.

---

## 6. Delivery roadmap

Each milestone below should end with a demonstrable vertical slice. Time estimates are intentionally omitted because scope depends on the audited repository and available weekly hours.

## Milestone 0 — Repository audit and engineering baseline

### Objective

Establish verified current state and make future changes safe.

### Tasks

- Inventory frontend, backend, database, migrations, Docker services, tests, and environment files.
- Map existing entities, endpoints, frontend pages, and major request flows.
- Run the existing application and record exact setup commands.
- Run all current tests, linting, formatting, and type checking.
- Find duplicated models/schemas, dead routes, unsafe secrets, and inconsistent naming.
- Document current Docker port mappings, especially PostgreSQL.
- Add or repair `.env.example` files without real secrets.
- Add a root README quick start if absent.
- Create architecture decision records (ADRs) for major decisions.
- Produce a gap report against Milestone 1.

### Deliverables

- `docs/current-state.md`
- `docs/architecture/system-context.md`
- `docs/adr/0001-modular-monolith.md`
- Reproducible local startup instructions
- Baseline CI or at minimum a single local validation command

### Exit criteria

- A new developer can start the stack from documented commands.
- Existing tests and checks have known pass/fail status.
- No secret is committed in tracked files.
- Current endpoint and schema inventory is documented.

---

## Milestone 1 — Complete the core restaurant workflow

### Objective

Finish only the CRUD and UI required for an end-to-end sale.

### Backend scope

- Restaurant CRUD.
- Menu CRUD scoped to a restaurant.
- Menu-item CRUD scoped through its menu/restaurant.
- Order creation with multiple items.
- Server-side lookup and calculation of item prices.
- Order retrieval and paginated restaurant order list.
- Centralized order status transitions.
- Basic payment status or payment record without real payment-provider integration.
- Completed-order sales aggregation.
- Alembic migration for every schema change.

### Frontend scope

- Restaurant list/create/edit/delete with clear error and loading states.
- Select a restaurant and retain active context cleanly.
- Menu and menu-item management.
- Order-entry screen.
- Kitchen/employee order list with status actions.
- Basic analytics cards: revenue, completed orders, average order value, top items.
- Empty, loading, validation, not-found, and API-error states.

### Required tests

- Cannot add an item from another restaurant to an order.
- Disabled/unavailable item cannot be newly ordered.
- Client-supplied price is ignored or rejected.
- Line totals and order total are correct.
- Invalid status transition is rejected.
- Cancelled orders do not count as completed revenue.
- Deleting/deactivating a menu item does not corrupt historic order items.

### Exit criteria

- The full restaurant -> menu -> item -> order -> completed sale -> dashboard path works.
- Database can be created from zero using migrations.
- OpenAPI reflects the implemented request/response schemas.
- Critical flow has integration tests.

---

## Milestone 2 — Refactor to maintainable application boundaries

### Objective

Create clear places for business rules before adding identity, inventory, and asynchronous processing.

### Tasks

- Move complex business logic out of routers into application services.
- Introduce repositories where they improve testability or centralize queries.
- Centralize domain exceptions and HTTP error mapping.
- Establish transaction/session ownership rules.
- Separate ORM models from API schemas.
- Add configuration validation using a typed settings layer.
- Add structured logging with request IDs.
- Remove circular imports and hidden global session usage.
- Add static typing to important service/repository boundaries.

### Guardrails

- Do not rewrite every file solely to match a theoretical architecture.
- Do not introduce generic base repositories that hide useful SQL behavior.
- Keep commits small and behavior-preserving.
- Add characterization tests before moving risky code.

### Exit criteria

- Routers are thin for all critical write flows.
- Order business rules are testable without making HTTP requests.
- Transaction boundaries are explicit.
- No regression in Milestone 1 behavior.

---

## Milestone 3 — Authentication and session security

### Objective

Replace anonymous access with secure user identity and renewable sessions.

### Scope

- User registration if appropriate for the product/demo.
- Login with email and password.
- Password hashing using Argon2id or a sound project-standard equivalent.
- Short-lived access JWT.
- Rotating refresh token with server-side session record.
- Logout/revoke current session and optionally all sessions.
- `GET /auth/me`.
- Rate limiting for login and refresh.
- Secure cookie strategy for browser sessions, or carefully documented token storage if current architecture requires it.
- CORS and CSRF threat model appropriate to the selected transport.
- Account status checks and generic login errors.

### Security requirements

- Secrets come from environment/secret management and fail fast when absent.
- Never place refresh tokens in logs.
- Store only a hash/identifier of refresh tokens server-side.
- Detect refresh-token reuse and revoke the affected token family.
- Use explicit issuer, audience, expiry, and algorithm verification for JWTs.
- Do not create a custom cryptographic scheme.

### Required tests

- Correct login succeeds; incorrect password produces generic failure.
- Expired access token is rejected.
- Refresh rotates tokens.
- Reusing a rotated token revokes the session family.
- Logout makes refresh impossible.
- Disabled user cannot authenticate.

### Exit criteria

- Protected routes require authentication.
- Browser refresh preserves a valid session safely.
- Authentication tests cover happy path and abuse cases.

---

## Milestone 4 — Multi-tenancy and RBAC

### Objective

Make organization and restaurant boundaries enforceable and demonstrably safe.

### Scope

- Organization and membership models.
- Organization owner bootstrap flow.
- Restaurant belongs to exactly one organization.
- Membership and optional restaurant assignment.
- Permission mapping for owner, manager, employee, and kitchen roles.
- Reusable authorization dependency/policy layer.
- Tenant-scoped repositories and queries.
- Staff invitation can initially be represented by an admin-created membership; email invitation may come later.
- Audit entries for membership, permission, menu, and order-sensitive actions.

### Critical rule

A URL or payload containing `organization_id` or `restaurant_id` is never proof of access. Authorization must verify the authenticated user's active membership and permissions.

### Migration strategy

- Backfill existing restaurants into a clearly named development organization.
- Backfill an owner account through an explicit script or migration-safe bootstrap command.
- Make tenant foreign keys non-null only after verified backfill.
- Document rollback and backup procedure before destructive constraint changes.

### Required tests

- User from organization A cannot read or mutate organization B data.
- Employee cannot manage staff or financial analytics.
- Manager cannot promote self to owner.
- Kitchen role can update allowed order statuses but cannot edit menu prices.
- Removed membership immediately loses access.
- List endpoints never leak cross-tenant rows.

### Exit criteria

- Every business endpoint has an explicit access policy.
- Cross-tenant integration tests cover reads, writes, nested IDs, and list endpoints.
- Audit log captures sensitive mutations without secrets.

---

## Milestone 5 — Transactional ordering and inventory

### Objective

Turn order creation into a realistic consistency-sensitive workflow.

### Scope

- Ingredient, recipe component, inventory movement, and balance models.
- Transactionally create an order and its items.
- Validate all menu items and availability.
- Snapshot item names/prices.
- Calculate totals server-side.
- Reserve or consume inventory according to one documented policy.
- Roll back the entire operation on any failure.
- Record adjustment and reversal movements instead of deleting ledger history.
- Use row locking or optimistic version checks to prevent overselling.
- Add an idempotency key to order submission.
- Define cancellation behavior and inventory compensation.

### Recommended initial inventory policy

For simplicity, consume inventory when an order is accepted and reverse it if an accepted order is cancelled. Document why this was chosen. Do not silently mix reservation and consumption semantics.

### Required tests

- Insufficient inventory rejects or flags an order according to policy.
- Concurrent orders cannot drive controlled stock below allowed limits.
- Failure during any item write rolls back the order and inventory changes.
- Duplicate idempotency key with identical request returns the original result.
- Same key with a different request is rejected.
- Cancellation creates compensating ledger movements exactly once.

### Exit criteria

- Transaction and concurrency behavior is documented.
- Inventory is auditable from movements.
- A concurrency test proves the selected locking/version strategy.

---

## Milestone 6 — Test architecture and quality gates

### Objective

Make safe, repeatable change a core feature of the project.

Testing should start earlier; this milestone completes the full strategy.

### Backend test layers

- Unit tests for state transitions, permission policies, totals, and inventory math.
- Repository integration tests against real PostgreSQL.
- API integration tests for authentication, tenant isolation, and workflows.
- Worker/event tests.
- Migration test from a clean database and, where practical, from a representative previous revision.

### Frontend test layers

- Component tests for important forms and state handling.
- API client tests/mocks where useful.
- End-to-end tests for login, restaurant selection, order flow, and permission restrictions.

### Quality tooling

- Backend formatter/linter and type checker.
- Frontend ESLint, formatting, and TypeScript checks.
- Coverage reports used as feedback, not as a gamed vanity metric.
- Pre-commit hooks only if they remain fast and documented.

### CI gates

- Dependency installation with lockfiles.
- Lint/format verification.
- Type checks.
- Backend tests with PostgreSQL and Redis services.
- Frontend tests.
- Production builds for backend image and frontend.
- Migration smoke test.

### Exit criteria

- A single documented command runs local validation.
- Pull requests cannot merge in the chosen workflow when required checks fail.
- Critical business rules and isolation boundaries have regression tests.

---

## Milestone 7 — Redis caching and rate limiting

### Objective

Use Redis for measured performance and ephemeral coordination needs.

### Initial uses

- Cache active restaurant menu reads.
- Rate-limit authentication and expensive AI endpoints.
- Optional short-lived dashboard cache.
- Store lightweight coordination state only where loss is acceptable or recoverable.

### Cache design

- Namespaced keys include environment and restaurant/tenant scope.
- Cache entries have TTLs.
- Menu writes invalidate the affected restaurant/menu cache.
- Never cache permission decisions longer than is safe.
- The application remains correct when Redis is unavailable; degraded behavior is documented.
- Avoid caching before obtaining baseline query and latency measurements.

### Measurement

Record before/after for a defined workload:

- P50, P95, and P99 latency.
- PostgreSQL query count.
- Cache hit ratio.
- Error rate.
- Test dataset size and hardware/environment.

### Exit criteria

- Cache correctness/invalidation tests pass.
- Benchmarks are reproducible from scripts.
- README claims only measured results.

---

## Milestone 8 — Reliable background jobs and domain events

### Objective

Decouple non-critical work without losing events or duplicating side effects.

### Recommended evolution

1. PostgreSQL transactional outbox as the source of publishable events.
2. A worker publishes/processes outbox records.
3. Use Redis Streams or a task queue compatible with the stack for delivery.
4. Add RabbitMQ/Kafka only if a later requirement justifies the operational cost.

### Initial events

- `order.submitted.v1`
- `order.accepted.v1`
- `order.completed.v1`
- `order.cancelled.v1`
- `menu.updated.v1`
- `inventory.low.v1`

### Initial consumers

- Analytics aggregate updater.
- Low-stock alert generator.
- Notification stub/log sink.
- Forecast feature refresh trigger later.

### Reliability requirements

- Stable event ID and schema version.
- At-least-once delivery assumed.
- Consumers are idempotent.
- Unique consumer receipt prevents duplicate side effects.
- Retry with bounded exponential backoff.
- Failed-event/dead-letter handling with inspection and replay procedure.
- Correlation/trace IDs propagate from request to event and worker.

### Required failure tests

- API process crashes after DB commit but before publication.
- Worker processes the same event twice.
- Consumer dependency is temporarily unavailable.
- Poison event exceeds retry limit.
- Old event version is handled or rejected clearly.

### Exit criteria

- No committed business event is silently lost under tested failure scenarios.
- Duplicate delivery does not duplicate analytics or notifications.
- Operator can inspect and replay failed work safely.

---

## Milestone 9 — Production containers, CI/CD, and deployment

### Objective

Deploy a reproducible, secure staging/demo environment.

### Container scope

- Multi-stage production images.
- Non-root runtime user.
- Health/readiness checks.
- Small build context and explicit `.dockerignore`.
- Separate development and production configuration.
- No secrets baked into images.
- Database migrations run as a controlled release step, not concurrently from every replica.

### Initial deployment shape

- Managed PostgreSQL.
- Managed Redis if affordable.
- Backend API container.
- Worker container using the same versioned image where practical.
- Next.js deployment.
- S3-compatible object storage for documents/model artifacts as needed.
- TLS and a stable demo URL.

### CI/CD stages

```text
pull request -> lint/type/test/build/security checks
merge to main -> build immutable images -> deploy staging -> migrate -> smoke test
tag/release -> deploy production/demo with approval strategy
```

### Infrastructure as code

Introduce Terraform after a manual deployment teaches the required resources. Keep secrets outside Terraform state where possible and document state handling.

### Exit criteria

- A clean commit can be deployed reproducibly.
- Migration failure stops deployment safely.
- Rollback/runbook is documented and tested at least once in staging.
- Demo data contains no real personal or payment information.

---

## Milestone 10 — Observability and operational readiness

### Objective

Make failures and performance understandable without attaching a debugger.

### Instrumentation

- Structured JSON logs.
- OpenTelemetry traces across frontend/backend where practical, DB, Redis, event publication, and workers.
- Prometheus-compatible metrics.
- Grafana dashboards or an equivalent hosted stack.
- Error tracking with sensitive-data filtering.

### Core metrics

| Area | Metrics |
|---|---|
| API | request rate, error rate, P50/P95/P99 latency, in-flight requests |
| Database | query duration, connection pool usage, slow queries, transaction failures |
| Redis | hit rate, latency, errors, evictions |
| Worker | queue depth, event age, throughput, retry and dead-letter counts |
| Business | submitted/completed/cancelled orders, revenue aggregates, stockout events |
| AI later | tool failures, grounded-answer rate, latency, tokens, cost, refusal rate |

### Operational artifacts

- Health and readiness endpoints.
- Service-level objectives for the demo, based on realistic measurements.
- Alerts for sustained error rate, DB saturation, old queued events, and repeated job failure.
- Runbooks for DB connection exhaustion, failed migration, Redis outage, queue backlog, and rollback.

### Exit criteria

- A request can be followed through API, database, outbox, and worker using a trace/correlation ID.
- A deliberately injected failure appears in dashboards/logs and has a documented response.

---

## Milestone 11 — Analytics data model

### Objective

Build reliable management metrics before ML or LLM features.

### Metrics

- Gross revenue and completed revenue by period.
- Order count and average order value.
- Sales by item/category/hour/day.
- Cancellation/refund rate.
- Item availability duration.
- Inventory usage, waste, and stockout frequency.
- Comparison with prior equivalent period.

### Design choices

- Begin with well-indexed SQL queries/views.
- Add aggregate tables/materialized views only when measurements justify them.
- Define metric semantics in a data dictionary.
- Use restaurant timezone when grouping business days.
- Never allow the frontend and backend to implement different revenue definitions.

### Data quality tests

- Completed/cancelled/refunded states map to metrics correctly.
- Timezone/day boundaries are correct.
- Aggregate equals known fixture totals.
- Duplicate events do not double count.
- Late events can be reconciled.

### Exit criteria

- Dashboard metrics have documented definitions and verified fixture results.
- Analytics queries have explain plans and appropriate indexes for the test dataset.

---

## Milestone 12 — Demand forecasting experiment

### Objective

Build a real, evaluated ML feature that predicts menu-item demand and supports inventory decisions.

### Data prerequisites

- Sufficient historical orders with restaurant, item, quantity, status, and timestamp.
- Synthetic data generator for development clearly labeled as synthetic.
- No leakage from cancelled orders or future information.
- Data validation and a versioned training snapshot.

### Problem definition

Start with a narrow target such as:

> Predict next-day quantity sold per active menu item for each restaurant.

Potential features:

- Day of week and holiday/calendar features.
- Recent lagged sales and rolling averages.
- Item/category identifiers.
- Availability and stockout indicators.
- Promotions when implemented.
- Weather only after the basic model and data contracts work.

### Experiments

Compare at minimum:

- Naive previous-period baseline.
- Seasonal moving average baseline.
- Gradient-boosted tree model.
- More complex sequence model only if data volume supports it.

Use time-based train/validation/test splits, never random splits for temporal forecasting.

### Metrics

- MAE.
- RMSE.
- WAPE or carefully handled MAPE.
- Bias/mean error.
- Metrics by restaurant and item demand segment.
- Prediction interval coverage if intervals are provided.

### MLOps scope

- Reproducible training command/pipeline.
- Experiment tracking, e.g. MLflow.
- Dataset/model version metadata.
- Model registry or clear artifact promotion process.
- Batch inference job.
- Prediction storage with model version and generated timestamp.
- Drift/data-quality monitoring.
- Retraining is scheduled only after a reasoned cadence is established.

### Product integration

- Forecast dashboard with uncertainty, not only a single number.
- Compare forecast with available inventory and recipe needs.
- Generate explainable shortage recommendations.
- Clearly label forecasts and limitations.

### Exit criteria

- Best model beats a meaningful baseline on held-out future data.
- Experiment can be reproduced from documented commands.
- UI displays model version, forecast time, horizon, and uncertainty.
- README reports only real evaluation results and dataset limitations.

---

## Milestone 13 — Anomaly detection and operational alerts

### Objective

Detect unusual operational patterns and produce reviewable, non-accusatory alerts.

### Initial anomaly families

- Revenue/order volume significantly below expected baseline.
- Unusually high cancellation or refund frequency.
- Ingredient consumption inconsistent with completed sales.
- Sudden stock adjustments or waste increases.

### Approach

1. Begin with explainable statistical rules and seasonal baselines.
2. Establish labeled or reviewed evaluation cases.
3. Compare Isolation Forest or another unsupervised model only where useful.
4. Treat alerts as signals requiring human review, never proof of theft or misconduct.

### Evaluation

- Precision on reviewed alerts.
- Recall on injected/known anomalies where possible.
- Alerts per restaurant per week.
- Time to detection.
- False-positive analysis by anomaly type.

### Exit criteria

- Every alert shows contributing evidence and baseline comparison.
- User can acknowledge/dismiss an alert and optionally provide feedback.
- Language avoids unsupported accusations.

---

## Milestone 14 — Document ingestion and evaluated Thai/English RAG

### Objective

Answer questions from restaurant documents with citations and measurable retrieval quality.

### Document types

- Standard operating procedures.
- Employee handbook.
- Recipes and preparation instructions.
- Food-safety guidance.
- Supplier terms and promotion rules.

### Secure ingestion pipeline

```text
upload -> validate type/size -> malware-safe handling strategy -> extract text
-> normalize -> chunk -> embed -> index -> retrieval evaluation
```

### Retrieval design

- PostgreSQL + pgvector for dense search.
- Lexical search using PostgreSQL full-text search or a justified BM25 engine.
- Hybrid retrieval.
- Optional reranker.
- Metadata filters enforce organization/restaurant/document access.
- Citations point to document and page/section/chunk metadata.

### Thai-language experiments

- Whitespace-naive vs Thai-aware segmentation.
- Multiple chunk sizes and overlaps.
- Thai/multilingual embedding models.
- Dense vs lexical vs hybrid retrieval.
- Reranker vs no reranker.

### Evaluation set

Create a versioned set of answerable, unanswerable, and adversarial questions. Keep evaluation questions separate from tuning decisions where possible.

### Metrics

- Recall@K.
- MRR or NDCG.
- Answer correctness.
- Faithfulness/groundedness with human review on a sample.
- Citation correctness.
- Abstention accuracy for unsupported questions.
- P50/P95 latency and cost per query.

### Security

- Documents are tenant-isolated at storage and retrieval layers.
- Retrieved text is untrusted data, not executable instructions.
- Defend against prompt injection in uploaded documents.
- Never allow documents to grant permissions or invoke tools.

### Exit criteria

- Cross-tenant retrieval tests pass.
- Answers cite supporting sources or explicitly abstain.
- Benchmark scripts and results are checked into the project.

---

## Milestone 15 — Restaurant AI analyst

### Objective

Build a constrained analyst that answers operational questions using verified tools and cites its evidence.

### Supported question examples

- Why did revenue decrease yesterday compared with last Tuesday?
- Which menu items caused the largest change in dinner sales?
- Which ingredients are at risk of shortage tomorrow?
- What does our closing SOP require?

### Tool design

Prefer narrow, typed, read-only tools:

- `get_revenue_summary`
- `compare_periods`
- `get_item_sales_breakdown`
- `get_stockout_periods`
- `get_inventory_forecast`
- `search_documents`

Do not initially give the model arbitrary database credentials or unrestricted SQL execution. If a read-only SQL tool is later added:

- Use a read-only DB role.
- Allowlist schemas/tables or use a semantic layer.
- Parse/validate queries.
- Enforce tenant filters outside model control.
- Set row, cost, and time limits.
- Block writes, DDL, multi-statements, and unsafe functions.

### Answer contract

Each answer should contain:

- Direct conclusion.
- Comparison period and metric definitions.
- Evidence/data points.
- Document citations where applicable.
- Limitations or uncertainty.
- No invented causality; distinguish correlation from explanation.

### Evaluation

- Tool-selection accuracy.
- Argument correctness.
- Final-answer numerical accuracy.
- Tenant isolation/adversarial access tests.
- Faithfulness and citation correctness.
- Unsupported-question abstention.
- Latency and cost.

### Exit criteria

- The agent cannot bypass authorization through prompts or tool arguments.
- Golden evaluation cases run automatically.
- Numerical answers are reproduced from deterministic tool outputs.
- UI exposes evidence and lets users inspect the supporting data.

---

## Milestone 16 — Performance, resilience, and portfolio proof

### Objective

Measure the system honestly, improve real bottlenecks, and package the project professionally.

### Load testing

Create reproducible k6 or equivalent scenarios:

- Login/refresh mix.
- Menu browsing.
- Order creation under concurrent inventory access.
- Order status updates.
- Dashboard reads.
- AI query tests separately because cost/latency characteristics differ.

Record:

- Test environment and dataset size.
- Virtual users and duration.
- Throughput.
- P50/P95/P99 latency.
- Error rate.
- CPU/memory/database/Redis utilization.
- Bottleneck found and change made.
- Before/after comparison.

Do not use a target such as “1,000 concurrent users” as a claim until it is actually achieved under a defined scenario.

### Resilience exercises

- Restart worker during queued work.
- Temporarily disable Redis.
- Kill an API replica during requests.
- Simulate slow database queries.
- Retry duplicate events.
- Restore database from backup in staging.

### Portfolio artifacts

- Architecture diagram.
- ER diagram.
- Key sequence diagrams for order transaction and event publication.
- Short demo video/GIF.
- Screenshots of dashboards and traces.
- API docs link.
- Benchmark report.
- ML model card and evaluation report.
- Threat model and security notes.
- ADRs showing trade-offs.

### Exit criteria

- README describes a reproducible deployed system, not aspirations.
- At least one measured performance improvement is documented.
- Demo account/data reset strategy exists.
- Recruiter can understand the value and engineering depth in under two minutes.

---

## 7. Cross-cutting backlog

These concerns must be addressed continuously rather than postponed to one phase.

### Security

- OWASP-oriented threat modeling.
- Dependency and container vulnerability scanning.
- Secret scanning.
- Least-privilege database and cloud identities.
- Input validation, output encoding, upload limits, and safe error handling.
- Audit sensitive changes.
- Data retention and deletion policy.
- Backups and restore tests.

### Database discipline

- Every schema change uses Alembic.
- Review autogenerated migrations manually.
- Add constraints and indexes deliberately.
- Back up before destructive migrations.
- Separate schema migration from large data backfill where needed.
- Inspect query plans for slow paths.

### Frontend quality

- Accessible forms and keyboard navigation.
- Mobile-friendly restaurant workflows.
- Consistent component and feature organization.
- Generated or shared API types if it reduces drift.
- Centralized API client and auth refresh handling.
- Optimistic updates only where rollback/error UX is clear.

### Documentation

- Keep setup commands executable.
- Document configuration and environment variables.
- Add ADRs for important irreversible decisions.
- Keep API examples synchronized.
- Maintain a changelog or release notes for meaningful milestones.

---

## 8. Dependency order and parallel-safe work

Primary dependency chain:

```text
Audit
  -> core workflow
  -> backend boundaries
  -> authentication
  -> tenancy/RBAC
  -> transactional inventory
  -> events/deployment/observability
  -> analytics
  -> ML and anomaly detection
  -> RAG and AI analyst
  -> performance proof
```

Work that can happen alongside the primary chain:

- Tests should be added with every milestone.
- README and ADRs evolve continuously.
- Frontend UX can advance once API contracts for that slice stabilize.
- Synthetic data generation can begin after the order schema stabilizes.
- Deployment foundations can begin while event work is being tested.
- RAG dataset planning can begin early, but production integration waits for identity and tenant isolation.

---

## 9. Definition of done for every milestone

A milestone is complete only when:

- Scope and acceptance criteria are met.
- Automated tests cover its critical behavior and failure paths.
- Linters, type checks, tests, and production builds pass.
- Migrations work from a clean database.
- Security and tenant implications were reviewed.
- Logs and errors are actionable and contain no secrets.
- API/OpenAPI and relevant user documentation are updated.
- No placeholder metrics or fake claims are presented as results.
- The feature is demonstrable through the UI or a documented API workflow.
- Known limitations and deferred work are recorded.

---

## 10. Git and execution strategy for Codex

### Branch/commit strategy

Use small, reviewable branches or commits by vertical slice, for example:

- `feat/order-state-machine`
- `feat/auth-refresh-rotation`
- `feat/tenant-policy-layer`
- `feat/inventory-ledger`
- `infra/transactional-outbox`
- `test/cross-tenant-isolation`

Each commit should leave the project in a coherent state when practical. Never combine a repository-wide formatting rewrite with a behavioral feature.

### Required agent behavior

Before modifying code, the agent must:

1. Inspect current files and git status.
2. Locate project instructions and existing conventions.
3. Identify current implementation relevant to the milestone.
4. State assumptions and list files expected to change.
5. Warn about destructive or irreversible migrations.

During implementation, the agent must:

- Preserve user changes and avoid destructive git commands.
- Use existing libraries unless replacement has a documented benefit.
- Add migrations rather than editing production schema manually.
- Add tests with the implementation, not as an indefinite later step.
- Avoid unrelated refactors.
- Prefer a complete vertical slice over many unfinished modules.

Before finishing, the agent must:

1. Run relevant tests, linting, typing, and builds.
2. Report exact commands and whether they passed.
3. Summarize schema/API behavior changes.
4. List remaining risks or follow-up work.
5. Update roadmap checkboxes/status and relevant docs.

---

## 11. First execution brief for Sol

Copy the following prompt into Codex while it is opened at the RestaurantOS repository:

```text
Read RestaurantOS_Master_Roadmap.md completely, then audit this repository.

For this turn, do not implement the entire roadmap. Work only on Milestone 0: Repository audit and engineering baseline.

Tasks:
1. Read every applicable AGENTS.md and the root README.
2. Inspect git status without discarding or overwriting existing changes.
3. Map the frontend, backend, Docker services, database models, Alembic migrations, endpoints, tests, and environment configuration.
4. Run the existing documented checks/startup workflow where safe.
5. Compare actual implementation with the assumptions and Milestone 1 requirements in the roadmap.
6. Create or update:
   - docs/current-state.md
   - docs/architecture/system-context.md
   - docs/adr/0001-modular-monolith.md
   - the root README quick-start section if it is missing or inaccurate
7. Update the “Current-state assumptions” section of the roadmap with verified facts.
8. Do not perform a broad refactor or add major product features in this milestone.

Before editing, give me a concise audit summary and proposed file changes. After implementation, run relevant validation and report exact results, remaining failures, and the recommended first Milestone 1 vertical slice.
```

After Milestone 0, give Sol only one milestone or vertical slice at a time. A strong next prompt will reference the roadmap, name the exact acceptance criteria, and ask Sol to inspect the current implementation before choosing changes.

---

## 12. Recommended milestone tracking

| Milestone | Status | Evidence/link |
|---|---|---|
| 0. Repository audit and baseline | Not started | |
| 1. Core restaurant workflow | Partially implemented; verify | |
| 2. Application boundaries | Not verified | |
| 3. Authentication | Not verified | |
| 4. Multi-tenancy and RBAC | Not started/verify | |
| 5. Transactional ordering and inventory | Not started/verify | |
| 6. Test architecture and quality gates | Not verified | |
| 7. Redis caching and rate limiting | Not started/verify | |
| 8. Background jobs and events | Not started/verify | |
| 9. Containers, CI/CD, deployment | Not verified | |
| 10. Observability | Not started/verify | |
| 11. Analytics model | Early work/verify | |
| 12. Demand forecasting | Not started | |
| 13. Anomaly detection | Not started | |
| 14. Evaluated RAG | Not started | |
| 15. AI analyst | Not started | |
| 16. Performance and portfolio proof | Not started | |

---

## 13. Final portfolio success criteria

RestaurantOS is portfolio-ready when a reviewer can verify that it:

- Runs locally from clear instructions and has a live demo.
- Supports a secure multi-tenant end-to-end restaurant workflow.
- Enforces permissions and tenant isolation with automated tests.
- Handles order and inventory writes transactionally under concurrency.
- Processes asynchronous events idempotently.
- Has CI/CD, observability, runbooks, and a tested deployment.
- Reports defined analytics correctly.
- Evaluates forecasting against real baselines.
- Evaluates Thai/English retrieval and cites sources.
- Constrains the AI analyst with deterministic tools and authorization.
- Publishes reproducible performance and quality measurements.
- Explains important trade-offs through concise ADRs and documentation.

The aim is not to maximize the number of technologies. The aim is to show that each technology solves a concrete problem, is tested, is observable, and can be explained clearly in an interview.
