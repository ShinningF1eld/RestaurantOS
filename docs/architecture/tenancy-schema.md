# Milestone 4: tenancy and authorization

Implemented in code on 2026-10-02; PostgreSQL acceptance and live cutover are
pending because the user requested deferring database tests while Docker fails.
The earlier schema-only slice was verified on 2026-10-01; that evidence does not
verify the new constraint migration or access behavior.

The modular monolith uses `app/modules` for auth, tenancy, audit, restaurants,
catalog, orders and analytics. Each feature owns `service.py`, `domain/` and
`repo/`, plus HTTP adapters as needed. Domain code has no HTTP/database imports;
services enforce policies and own write transactions; repositories never commit.
Shared Base/session infrastructure lives in `app/db`. The former layer-first
files are compatibility import facades with no separate implementation. See
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

[Cutover, backups, rollback and deferred acceptance](../runbooks/tenancy.md)
include the exact migration/bootstrap commands. Both revisions must be applied
before running this version of the API. The live database was not modified by
this implementation; its existing restaurant/user assignment is still pending.

Tests are present for schema integrity, every cross-tenant direct/nested read and
write, collection/count scope, Employee limitations, Manager self-promotion,
revocation, live role/assignment changes, bootstrap, safe audit facts and atomic
failure. Unit tests compile real PostgreSQL scope predicates without connecting.
The database-backed integration, migration rehearsal and browser suites were not
run in this pass. These are still required before declaring Milestone 4 fully
verified against its exit criteria.
