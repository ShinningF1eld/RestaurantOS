# ADR 0002: Introduce feature modules incrementally

- Status: Accepted
- Date: 2026-09-30

Milestone 2 established service-owned transactions and repository boundaries.
Milestone 3 introduces `app/modules/auth` with its own router, API schemas,
service, domain policies, repositories/models, and security adapters.

Keep dependency direction router -> service -> domain/repository. The service
coordinates writes; domain code has no HTTP or persistence imports; repositories
never commit. Reuse the shared SQLAlchemy Base and connection infrastructure.
Other features depend on auth's immutable principal dependency, not its tables.

Existing layer-first features coexist with modules. Move catalog and subsequent
features when substantive work justifies touching them. Moving Python files
does not imply changing database names or public API contracts. No generic base
repository, separate auth database, or repository-wide rewrite is introduced.

This temporarily permits two folder conventions in exchange for smaller,
reviewable changes. All new auth code belongs in the auth module.
