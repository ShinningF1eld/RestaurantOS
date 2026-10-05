# Menu recipes

Recipes express ingredient quantities for **one portion**, using each ingredient's
fixed inventory base unit (`g`, `ml`, or `piece`). Quantities are positive decimal
strings, with at most three decimal places and a maximum of `999999999.999`.
An ingredient may appear only once per recipe and must be active and belong to
the menu item's restaurant. No automatic unit conversion is performed.

`GET /menu-items/{menu_item_id}/recipe` requires `menu.read` and returns
`menu_item_id`, `restaurant_id`, `inventory_tracking`, and `components` containing
`ingredient_id`, `ingredient_name`, `unit`, and `quantity`.

`PUT /menu-items/{menu_item_id}/recipe` requires `menu.manage`, available to
Owners and assigned Managers. It accepts the complete desired recipe:

```json
{
  "inventory_tracking": true,
  "components": [
    {"ingredient_id": 1, "quantity": "150"},
    {"ingredient_id": 2, "quantity": "100"}
  ]
}
```

Enabling tracking requires a nonempty valid recipe. Existing menu items remain
untracked after migration; empty recipes cannot silently bypass stock control
for tracked items. Disabling tracking is an explicit management action. Recipe
replacement and its audit fact commit together, after locking the restaurant
row and menu item. Stock-changing operations use the same restaurant lock.

Menu item responses include `inventory_tracking`, `out_of_stock`, and
`available_portions`. These are computed from a single database snapshot of
the recipe and balances. A tracked item with missing, inactive, or insufficient
ingredients is out of stock. Available portions are the smallest number of
complete portions supported by any component; untracked items return `null`.
The menu and recipe editor refresh stock on focus and periodically while visible.

Deleting an unused menu item also deletes its recipe components. The existing
deletion behavior for an item with order history deactivates it, preserving
historical orders and stock history.

The selected order policy is **consume on acceptance and never restore stock on
cancellation**. This overrides the roadmap's earlier proposed reversal policy.
Cancelled accepted orders retain their original consumption; cancellation must
not also record an automatic waste deduction for those same ingredients.
