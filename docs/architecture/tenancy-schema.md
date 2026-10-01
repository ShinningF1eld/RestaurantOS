# Milestone 4: tenancy schema expansion

Implemented on 2026-10-01 as the schema/model slice only. Authorization, owner
bootstrap, membership APIs, and audit writers are not implemented yet. This
schema does not make the existing business endpoints tenant-isolated.

## Models and integrity

| Table | Purpose and constraints |
|---|---|
| `organizations` | UUID tenant root, unique normalized slug, nonblank name, active/archived status, timezone-aware timestamps |
| `memberships` | UUID user-to-organization membership, unique user/org pair, active/revoked status, exactly OWNER/MANAGER/EMPLOYEE |
| `restaurants` | Nullable organization FK and lookup index during expansion; unique id/org pair supports composite tenant FKs |
| `restaurant_assignments` | Unique membership/restaurant pair; composite FKs require membership and restaurant to belong to the same organization |
| `audit_entries` | Organization, optional restaurant and actor, action/resource snapshot, JSON-object change summary, request ID, UTC timestamp |

New models reuse the shared SQLAlchemy Base and are explicitly registered in
application startup and Alembic, as with auth. Organization/membership/assignment/audit
links use restrictive deletion to avoid silently cascading business or audit
history. An audit actor can be set to null when an otherwise unreferenced user
is deleted; resource IDs are snapshots without a resource FK.

The role model follows the user's three-role decision. Planned permissions:

- OWNER: organization-wide restaurant/catalog/order/analytics operations and
  membership/ownership administration.
- MANAGER: assigned-restaurant profile, catalog, operational order and payment
  management, and analytics; no staff or ownership administration.
- EMPLOYEE: assigned-restaurant operational reads and only ACCEPTED -> PREPARING
  and PREPARING -> READY updates. This takes the previously proposed kitchen
  role's permissions, not the previous cashier/employee permissions. No order
  creation, item/payment changes, completion/cancellation, staff administration,
  financial analytics, or menu price changes.

These are intended policy semantics, not enforced capabilities in this slice.
Assignment-level role overrides are not introduced. Membership owns the role.
Future audit writers must allowlist safe changes and insert within the business
transaction. JSON-object validation alone does not sanitize secrets or enforce
append-only storage; those responsibilities remain in the audit implementation.

## Migration and cutover

`83c7e1b4a902` follows `72bd03a1f901` in the existing linear chain. It:

1. Creates the new tables and nullable restaurant organization FK.
2. Creates `RestaurantOS Development Workspace` (`restaurantos-development`).
3. Backfills every existing restaurant into that development organization.

It does not provision a user, promote an existing account, change auth sessions,
or rewrite menu/order/item snapshots. The restaurant FK has no server default;
the current creation service can still insert null organization IDs until the
next slice supplies authenticated membership scope.

Before changing a shared/application database, back up with PostgreSQL's normal
backup tooling and verify that restore is available. Apply the revision through
Alembic using the configured database. Before the contract migration, implement
the explicit idempotent owner bootstrap and tenant-aware restaurant creation;
then backfill any restaurants created during expansion, verify all tenant FKs,
and apply NOT NULL. Bootstrap must select an active owner explicitly rather than
granting all existing users access.

Application rollback can keep the additive schema. Downgrading to `72bd03a1f901`
preserves restaurant/catalog/order/auth rows but **deletes organizations,
memberships, assignments, audit entries, and restaurant tenant associations**.
Do not downgrade after real tenant usage without a verified backup and a data
recovery plan. The checker rehearses downgrade only on disposable data.

## Verification

From the repository root, with `TEST_DATABASE_URL` configured for local
PostgreSQL and ending in `_test`:

```powershell
backend/.venv/Scripts/python.exe scripts/check-tenancy-migration.py --run-tests
```

The checker creates randomly named disposable databases, rehearses clean and
previous-head upgrades, checks model drift, verifies legacy order snapshots and
user preservation across downgrade/re-upgrade, and optionally runs the complete
backend suite. It removes only databases successfully created by that invocation.
It does not migrate the application database or truncate the configured test DB.

`backend/tests/integration/test_tenancy_schema.py` verifies role constraints,
unique memberships/assignments, both cross-organization assignment directions,
cross-organization audit rejection, JSON-object summaries, restrictive tenant
deletion, UTC model round-trips, and audit preservation when its actor is deleted.

Verified locally: Ruff, full-app mypy, 163 backend tests (16 new schema tests),
clean/previous-head migration checks, downgrade/re-upgrade history preservation,
and no Alembic model drift. Validation used disposable databases only; the
application database was not migrated. Existing datetime/TestClient deprecation
warnings remain. No frontend code or browser behavior changed in this slice.
