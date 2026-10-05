# Inventory API

There is one logical inventory per restaurant. Ingredient rows attach directly
to the restaurant; there is no separate inventory-creation workflow or parent
inventory record. Inventory uses the existing authenticated
organization membership. Owners can access every restaurant in their
organization. Managers can access assigned restaurants. Both roles have
`inventory.read` and `inventory.manage`; Employees have neither capability.
The API returns not-found for restaurants and ingredients outside the caller's
scope.

All routes are under
`/api/restaurants/{restaurant_id}/inventory`. Quantities use the ingredient's
fixed base unit: grams (`g`), millilitres (`ml`), or pieces. Values are finite,
nonnegative, limited to three decimal places and at most `999999999.999`.
Opening quantities may be zero; receipt and waste amounts must be positive. A
physical count may be zero.

| Method and path | Capability | Behavior |
|---|---|---|
| `GET /ingredients?limit=100&offset=0` | `inventory.read` | Lists ingredients and their current balance, version, active state and low-stock flag. Limit is 1–100. |
| `POST /ingredients` | `inventory.manage` | Creates an ingredient and opening-balance movement atomically. Names are unique case-insensitively within a restaurant. |
| `PUT /ingredients/{ingredient_id}` | `inventory.manage` | Updates the name, unit, reorder threshold, and active/archive state. Archived ingredients remain visible in the list and history. |
| `POST /ingredients/{ingredient_id}/movements` | `inventory.manage` | Records a receipt, waste amount, or physical count. The balance and ledger entry commit together. |
| `GET /ingredients/{ingredient_id}/movements?limit=20&offset=0` | `inventory.read` | Lists newest movements first, including the balance after each movement, actor email when available, and reason. Limit is 1–100. |

Ingredient creation accepts `name`, `unit`, optional `reorder_threshold`,
optional `opening_quantity`, and an `idempotency_key`. Updating a unit is
rejected after the ingredient has any movement history. Archiving is rejected
while the balance is above zero; record waste or count the stock to zero first.
Creation always records an opening movement, even when the opening quantity is
zero, so the base unit is fixed after creation. An archived ingredient can be
restored and retains its history.

A movement accepts `kind` (`receipt`, `waste`, or `count`), `quantity`, a
required `reason`, and an `idempotency_key`. A count also requires
`expected_version`, copied from the current ingredient response. The API
rejects the count if another stock change has advanced that version, so the
operator can refresh and count again. Writes lock the restaurant row to
serialize concurrent inventory writes within that restaurant. Waste cannot
make the balance negative.

Idempotency keys contain 1–100 letters, digits, underscores or hyphens.
Ingredient creation checks opening-movement keys within the restaurant; a
replayed create returns the ingredient's current state. Stock-action keys are
scoped to an ingredient and share that ingredient's opening-movement key space;
a replay returns the original movement. Reusing a key with a different
payload returns a conflict. This supports retrying after a lost response
without recording the same stock change twice. The movement ledger is
append-only through the application API and services; the database does not
install a trigger to enforce append-only access.

Successful ingredient creation, edits, and stock changes also record scoped
audit facts. Inventory does not yet deduct stock from recipes or orders and has
no supplier, purchase-order, or inter-restaurant transfer workflow. Revision
`c48b7e02f315` adds the inventory tables after catalog-price revision
`b37a6d91e204`. The catalog-price revision is applied to the existing
application database; the inventory revision remains unapplied.
