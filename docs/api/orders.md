# Orders and transactional stock

Order routes use authenticated restaurant scope. Owners and assigned Managers
create, submit, accept, cancel, and delete orders. Employees retain their existing
kitchen-state permissions and cannot perform those management actions.

`POST /api/restaurants/{restaurant_id}/orders` requires an `idempotency_key`
containing 1–100 letters, digits, underscores, or hyphens, alongside the existing
order fields and item list. A key is scoped to the restaurant. Repeating the same
key and business payload returns the original creation response with status 201,
even if the order subsequently changed or an unconsumed order was deleted.
Changing the payload under that key returns 409. Replays do not create another
order or audit entry. The browser retains the key after an uncertain failure.

Existing `GET`, `PUT`, and `DELETE /api/orders/{order_id}` routes and paginated
`GET /api/restaurants/{restaurant_id}/orders` remain available. Missing keys and
invalid request fields return 422; unavailable catalog items and insufficient
tracked ingredients prevent ordering. The menu API exposes `out_of_stock` and
`available_portions`, and the order-entry screen disables out-of-stock items.
Availability is advisory until acceptance because drafts do not reserve stock.

| Order action | Stock effect |
|---|---|
| Create or edit a draft; submit | Validate current recipes and aggregate stock; no reservation or movement |
| Accept from submitted | Validate and consume all required ingredients in one transaction |
| Prepare, ready, complete | No additional consumption |
| Cancel at any allowed state | No stock return and no additional consumption |
| Delete | Reject with 409 when inventory movements reference the order |

The selected cancellation policy is **never restore ingredients**. Consumption
remains recorded even after cancellation or recipe changes. Do not record an
additional waste deduction for ingredients already consumed by that order.
Record waste separately for stock lost outside that consumption.

Every stock-sensitive write locks the restaurant row first. Order updates then
lock and refresh the order; acceptance aggregates requirements across all order
lines and locks ingredient balances in ascending ingredient-ID order. Recipe
changes and manual receipts, waste, and counts use the same restaurant lock.
This serializes changes within a branch and gives acceptance one consistent
recipe and balance view. Different restaurants can still proceed independently.

If any required ingredient is inactive, lacks a balance, or has insufficient
stock, acceptance returns 409 without changing the order, any balance, ledger,
or audit. Successful acceptance records one negative `consumption` movement per
ingredient with the actual base-unit quantity, order reference, operator, reason,
resulting balance, and incremented stock version. Audit, order, balance, and
movements commit together; a failure in any write rolls back all of them.
Database uniqueness on `(order_id, ingredient_id)` prevents duplicate
consumption. Same-state acceptance retries have no stock effect.

Migration `e68d9a24b537` follows recipe revision `d57c8f13a426` and preserves
existing orders as `inventory_processed=false`. No historical stock deductions
are inferred. New acceptance sets the flag, including deliberately untracked
items; already accepted legacy orders are not consumed retroactively. Migration
downgrade refuses to discard consumption, processed-order, or replay history.
Recipe tracking initially defaults to false for compatibility; tracked items
require a valid recipe. See [recipes](recipes.md) and [inventory](inventory.md).

Verification uses real PostgreSQL sessions and distinct users for competing
acceptance and same-key submission. Tests also overlap acceptance with manual
stock changes and recipe edits, reconcile ledger totals, inject both service and
database write failures, exercise legacy orders, and verify browser shortages.
Run `backend/.venv/Scripts/python.exe scripts/verify-milestone5.py --tests --browser`
from the repository root for disposable clean/previous-head migration and full
backend/browser verification. It does not migrate the application database.
