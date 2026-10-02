# Milestone 4: tenancy and authorization

Implemented and verified locally on 2026-10-02, including PostgreSQL acceptance
and live cutover. The earlier schema-only slice was verified on 2026-10-01.

The modular monolith uses `app/modules` for auth, tenancy, audit, restaurants,
catalog, orders and analytics. Each feature owns `service.py`, `domain/` and
`repo/`, plus HTTP adapters as needed. Domain code has no HTTP/database imports;
services enforce policies and own write transactions; repositories never commit.
Shared Base/session infrastructure lives in `app/db`. The unused top-level
business-layer compatibility folders have been removed. See
[ADR 0002](../adr/0002-feature-modules.md).

## Model integrity

| Table | Constraints and purpose |
|---|---|
| `organizations` | UUID storage ID, generated unique integer `number`, normalized unique slug, nonblank name, active/archived status, UTC timestamps |
| `memberships` | UUID ID; **unique user ID**, so one organization per user even after revocation; OWNER/MANAGER/EMPLOYEE only; active/revoked status |
| `restaurants` | Non-null single organization FK with no default; tenant-aware creation supplies scope; unique id/org pair supports composite FKs |
| `restaurant_assignments` | Unique membership/restaurant pair; composite FKs require both parents in the same organization |
| `audit_entries` | Organization, optional restaurant/actor, action/resource snapshots, JSON-object facts, request ID, UTC timestamp |

Tenant links use restrictive deletion to preserve history. Deleting an otherwise
unreferenced audit actor nulls its actor FK while retaining the audit record.
Resource IDs are snapshots, independent of resource deletion. Owners access all
branches in their organization; Managers/Employees need explicit assignments.
Assignments have no role override. Organization number **1** denotes the legacy
development organization while UUID storage IDs remain compatible with the
schema already introduced.

## Enforcement

The shared access service resolves current active membership, organization and
assignments from PostgreSQL on each operation. Capabilities and Employee status
rules are pure policies in tenancy's domain. Repositories scope direct lookups,
nested catalog/order references, lists, counts and analytics through the
restaurant's organization and assignments. Foreign/unassigned resources are 404;
forbidden operations are 403. Cookies still carry identity, not mutable roles.

Owner membership edits serialize on the organization row and protect the last
active Owner. Business writes acquire shared membership/assignment locks so
revocation cannot bypass an authorized write boundary. Status writes lock the
order before checking its transition. Audit facts are staged within the same
transaction; failures roll back the business mutation. Audit reads are Owner-only
and organization-scoped; no audit mutation API is exposed. See the complete
[role matrix, endpoint policies and demonstration](../api/tenancy.md).

## Migrations and verification

`83c7e1b4a902` follows `72bd03a1f901` and creates the tenant tables, development
organization and legacy restaurant backfill. It intentionally grants no user
access. `94d8f2c5b013` then rejects duplicate user memberships, fills remaining
null restaurant scope, numbers the development organization 1, enforces
restaurant NOT NULL and user-only membership uniqueness.

The explicit idempotent `app.modules.tenancy.cli bootstrap-existing` command
assigns the sole existing active user as Owner only after confirming the sole
restaurant belongs to development organization 1. For new accounts/workspaces,
`POST /api/organizations` creates the first Owner and organization atomically.

[Cutover, backups, rollback and acceptance](../runbooks/tenancy.md) include the
exact migration/bootstrap commands. Both revisions must be applied before running
this version of the API. The local live database is at `94d8f2c5b013`: restaurant 1
belongs to organization 1 and its sole existing user is Owner. Backup restoration
and original-data preservation were verified, and repeating bootstrap added no
duplicate membership or audit entry.

Tests are present for schema integrity, every cross-tenant direct/nested read and
write, collection/count scope, Employee limitations, Manager self-promotion,
revocation, live role/assignment changes, bootstrap, safe audit facts and atomic
failure. Unit tests compile real PostgreSQL scope predicates without connecting.
All 231 backend tests and 13 Chromium tests passed, including database-backed
integration and Employee permission checks. Clean/previous-head migrations,
drift detection and disposable downgrade/re-upgrade also passed. The Milestone 4
exit criteria are verified locally: all business endpoints have explicit policies,
cross-tenant reads/writes/nested IDs/lists are covered, and sensitive mutations
produce safe transactional audit facts.
