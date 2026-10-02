# Organization and role access

Business requests require the existing cookie session and an active membership
in an active organization. Each user has at most one membership, including a
revoked membership; each restaurant has one non-null organization FK. Organization
storage IDs remain UUIDs. `number` is a unique generated display number; the
migrated development organization has number **1**.

| Operation | Owner | Manager | Employee |
|---|---|---|---|
| Restaurant/menu/item/order reads | All own branches | Assigned branches | Assigned branches |
| Restaurant creation/deletion | Yes | No | No |
| Restaurant profile updates | Yes | Assigned branches | No |
| Menu/item create, update, delete, availability/price | Yes | Assigned branches | No |
| Order creation, details/items/payment changes | Yes | Assigned branches | No |
| Order status changes/cancellation/completion | Domain-valid transitions | Domain-valid transitions in assigned branches | ACCEPTED → PREPARING; PREPARING → READY only |
| Hard-delete order | Yes | No | No |
| Financial dashboard | Yes | Assigned branches | No |
| Membership/role/assignment administration | Yes | No | No |
| Audit inspection | Yes, own organization | No | No |

Named capabilities are defined in `modules/tenancy/domain/policies.py`. The
Employee role replaces the previously discussed kitchen role. Authorization
checks the **supplied field set** before any order mutation, including null
fields. Mixing an allowed status with `payment_status`, `items`, `notes`,
`customer_name` or `table_number` rejects the entire Employee request.

Foreign, unassigned and absent resources return the same `404`. An accessible
resource with a forbidden operation returns `403`. No membership or an archived
organization returns `403`. Authentication remains `401`; scope and roles are
loaded from PostgreSQL for each operation, without storing them in a JWT.
Restaurant creation accepts no organization ID: the service supplies it. Nested
item references must belong to the scoped order's restaurant. Lists, counts,
analytics and direct-ID lookups apply the same scope predicates.

## Administration contracts

Existing business URLs and response shapes are preserved. New routes:

| Route | Policy and response |
|---|---|
| `GET /api/access` | Active membership; organization UUID/number, role, capabilities, assigned restaurant IDs |
| `POST /api/organizations` | Authenticated provisioned user with no membership; atomically creates organization and OWNER membership; 201 |
| `GET /api/organization` | Current active membership; own organization only |
| `GET /api/memberships` | OWNER; own organization memberships, including revoked entries |
| `POST /api/memberships` | OWNER; existing active account's email, role, optional restaurant IDs; 201 |
| `PUT /api/memberships/{id}` | OWNER; optional role and replacement restaurant ID list |
| `DELETE /api/memberships/{id}` | OWNER; revokes membership; 204 |
| `GET /api/audit?limit=25&offset=0` | OWNER; own organization only, limit 1–100 |

Organization creation is the explicit first-owner policy for an unassigned
account. It grants no access to any existing organization. There is no public
account registration or email invitation. Account provisioning still uses the
auth operator CLI. Membership creation for an account that already has any
membership returns `409`; transferring or reactivating a revoked membership is
not exposed in this milestone. An Owner cannot remove or demote the last active
Owner. Organization row locking serializes owner administration; business writes
hold shared membership/assignment locks, so committed revocations prevent later
writes. Order updates lock their order before evaluating its current status.

## Manual API demonstration

Use FastAPI `/docs` with existing session cookies and trusted browser origin, or
an HTTP client that retains cookies and supplies `Origin: http://localhost:3000`
and `X-CSRF-Protection: 1` on mutations. Provision the accounts with the auth CLI
before login; do not embed passwords in scripts or documentation.

1. Log in as an unassigned account A and create an organization:
   `POST /api/organizations` with `{"name":"Workspace A","slug":"workspace-a"}`.
   Read `/api/access` and verify OWNER. Create restaurant A and its menu/item.
2. Repeat using account B for Workspace B and restaurant B. In A's session,
   restaurant B, B's menu/item/order IDs, their nested collections and analytics
   return 404. `/api/restaurants` contains only A's branches.
3. As A, add two provisioned accounts using `/api/memberships`, for example
   `{"email":"manager@example.test","role":"MANAGER","restaurant_ids":[123]}`
   and an EMPLOYEE payload with the same assigned restaurant. Replace `123` with
   restaurant A's actual ID. There is no tenant ID input.
4. Sign in as Manager. Menu edits and analytics work for assigned A; promoting
   that membership to OWNER is 403. Sign in as Employee: staff, analytics, menu
   price edits and order creation are 403.
5. As Owner submit and accept an order; as Employee update to PREPARING, then
   READY. Completion, cancellation and a mixed preparation/payment request are
   403. The UI exposes only those two preparation controls.
6. Revoke Employee as Owner. Its existing cookie can still identify the account
   at `/auth/me`, but business requests immediately return 403. Removing Manager's
   assignments changes branch access to 404 without logging in again.
7. Inspect `/api/audit` as Owner. Sensitive successful mutations have actor,
   organization/restaurant, action, resource ID, request ID and timestamp. Safe
   structured facts include roles, assignments, prices, order/payment status and
   totals; customer details, notes, passwords, cookies and tokens are excluded.

The Staff access screen supports adding provisioned accounts to its current
branch, changing roles and revoking access. The API also supports assignment
replacement across multiple branches. Audit entries are append-only through the
application and are inserted in the business transaction; a failed audit write
rolls back the mutation. Audit history restricts restaurant deletion; dependent
data returns 409. Remove menu items before deleting their menu.
