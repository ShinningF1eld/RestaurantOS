# ADR 0002: Introduce feature modules incrementally

- Status: Accepted
- Date: 2026-09-30
- Updated: 2026-10-02 (module layout confirmed)

Milestone 2 established service-owned transactions and repository boundaries.
Milestone 3 introduces `app/modules/auth` with its own router, API schemas,
service, domain policies, repositories/models, and security adapters.

`app/modules` is the primary home for business features in the modular monolith.
Use auth's internal structure consistently for tenancy, audit, and subsequent
features. Each module owns its HTTP boundary, application service, domain, and
persistence layer:

```text
app/modules/<feature>/
  __init__.py
  router.py             # HTTP endpoints, when needed
  schemas.py            # Pydantic request/response schemas
  dependencies.py       # HTTP dependency adapters, when needed
  service.py            # Use cases, authorization, transaction ownership
  domain/
    __init__.py
    policies.py         # Pure rules; additional roles/errors/value types as needed
  repo/
    __init__.py
    models.py           # SQLAlchemy models
    <queries>.py        # Feature-specific persistence operations
```

The service layer is `service.py`, matching auth; it does not require an extra
service directory. Add files as behavior is implemented rather than creating
empty layers. Tenancy, audit, restaurants, catalog, orders and analytics now follow this
layout, with pure commands/value types or policies in their domains.

Keep dependency direction router -> service -> domain/repository. The service
coordinates writes; domain code has no HTTP or persistence imports; repositories
never commit. Reuse the shared SQLAlchemy Base and connection infrastructure.
Other features depend on auth's immutable principal dependency, not its tables.

Shared configuration, database/session infrastructure, HTTP middleware, and
external adapters remain outside feature modules. Modules collaborate through
explicit service/domain interfaces rather than importing another module's
repositories or ORM tables into business logic. One PostgreSQL database and
shared transaction/session infrastructure remain in use.

Restaurant/catalog/order/analytics implementations now live in their modules.
The unused top-level `domain`, `repositories`, `services`, `routers` and `schemas`
compatibility folders have been removed. ORM tables and public business URLs
retain their names. `app/db/base.py`
is the shared metadata root; migrations register every module's models. No
separate databases, generic base repository or additional service directory is
introduced. Cross-feature relational joins remain in repositories; business
services use tenancy's public access/policy interface and audit's transaction
writer.
