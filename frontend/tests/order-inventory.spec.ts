import { randomUUID } from "node:crypto";
import {
  test,
  expect,
  signIn,
  catalog,
  ingredient,
  api,
  writeHeaders,
} from "./milestone5-fixtures";

test("order acceptance deducts once, rejects shortages, and cancellation never restores ingredients", async ({
  page,
  account,
}) => {
  await signIn(page, account);
  const { restaurantId, menuItemId } = await catalog(page);
  const chicken = await ingredient(page, restaurantId, "Chicken", "150");
  const rice = await ingredient(page, restaurantId, "Rice", "100");
  const recipe = await page.request.put(`${api}/menu-items/${menuItemId}/recipe`, {
    headers: writeHeaders,
    data: {
      inventory_tracking: true,
      components: [
        { ingredient_id: chicken.id, quantity: "150" },
        { ingredient_id: rice.id, quantity: "100" },
      ],
    },
  });
  expect(recipe.ok()).toBeTruthy();
  const ids: number[] = [];
  for (let index = 0; index < 2; index++) {
    const response = await page.request.post(`${api}/api/restaurants/${restaurantId}/orders`, {
      headers: writeHeaders,
      data: {
        idempotency_key: randomUUID(),
        items: [{ menu_item_id: menuItemId, quantity: 1 }],
      },
    });
    expect(response.status()).toBe(201);
    ids.push((await response.json()).order_id);
    expect(
      (
        await page.request.put(`${api}/api/orders/${ids[index]}`, {
          headers: writeHeaders,
          data: { status: "SUBMITTED" },
        })
      ).ok(),
    ).toBeTruthy();
  }
  const balances = async () =>
    (await (
      await page.request.get(`${api}/api/restaurants/${restaurantId}/inventory/ingredients`)
    ).json()) as { id: number; quantity: string }[];
  expect((await balances()).map((row) => row.quantity)).toEqual(["150.000", "100.000"]);
  await page.goto(`/restaurants/${restaurantId}/orders`);
  const first = page
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: `Order #${ids[0]}`, exact: true }) });
  const second = page
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: `Order #${ids[1]}`, exact: true }) });
  await first.getByRole("button", { name: "Mark accepted", exact: true }).click();
  await expect(first.getByRole("button", { name: "Mark preparing", exact: true })).toBeVisible();
  expect((await balances()).map((row) => row.quantity)).toEqual(["0.000", "0.000"]);
  await expect(page.getByLabel("Quantity for Chicken rice", { exact: true })).toBeDisabled();
  await expect(page.getByText("Out of stock", { exact: true })).toBeVisible();
  await second.getByRole("button", { name: "Mark accepted", exact: true }).click();
  await expect(second.getByRole("alert")).toContainText("Insufficient tracked stock");
  await expect(second.getByRole("button", { name: "Mark accepted", exact: true })).toBeVisible();
  await first.getByRole("button", { name: "Mark preparing", exact: true }).click();
  await expect(first.getByRole("button", { name: "Mark ready", exact: true })).toBeVisible();
  expect((await balances()).map((row) => row.quantity)).toEqual(["0.000", "0.000"]);
  for (const [item, quantity] of [
    [chicken, "150"],
    [rice, "100"],
  ] as const) {
    expect(
      (
        await page.request.post(
          `${api}/api/restaurants/${restaurantId}/inventory/ingredients/${item.id}/movements`,
          {
            headers: writeHeaders,
            data: {
              kind: "receipt",
              quantity,
              reason: "Delivery during service",
              idempotency_key: randomUUID(),
            },
          },
        )
      ).status(),
    ).toBe(201);
  }
  await page.getByRole("button", { name: "Refresh stock", exact: true }).click();
  await expect(page.getByLabel("Quantity for Chicken rice", { exact: true })).toBeEnabled();
  await second.getByRole("button", { name: "Mark accepted", exact: true }).click();
  await expect(second.getByRole("button", { name: "Mark preparing", exact: true })).toBeVisible();
  expect((await balances()).map((row) => row.quantity)).toEqual(["0.000", "0.000"]);
  expect(
    (
      await page.request.put(`${api}/menu-items/${menuItemId}/recipe`, {
        headers: writeHeaders,
        data: {
          inventory_tracking: true,
          components: [
            { ingredient_id: chicken.id, quantity: "75" },
            { ingredient_id: rice.id, quantity: "50" },
          ],
        },
      })
    ).ok(),
  ).toBeTruthy();
  await second.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(second.getByRole("button", { name: "Cancel", exact: true })).toBeHidden();
  expect((await balances()).map((row) => row.quantity)).toEqual(["0.000", "0.000"]);
  const history = await (
    await page.request.get(
      `${api}/api/restaurants/${restaurantId}/inventory/ingredients/${chicken.id}/movements`,
    )
  ).json();
  const consumed = history.filter((row: { kind: string }) => row.kind === "consumption");
  expect(consumed).toHaveLength(2);
  expect(consumed.map((row: { quantity_delta: string }) => row.quantity_delta)).toEqual([
    "-150.000",
    "-150.000",
  ]);
  expect(consumed.every((row: { actor_name: string }) => row.actor_name === account.email)).toBe(
    true,
  );
});

test("order entry retries a committed creation with the same key and one ticket", async ({
  page,
  account,
}) => {
  await signIn(page, account);
  const { restaurantId } = await catalog(page);
  await page.goto(`/restaurants/${restaurantId}/orders`);
  await page.getByLabel("Quantity for Chicken rice", { exact: true }).fill("1");
  const endpoint = `${api}/api/restaurants/${restaurantId}/orders`;
  const keys: string[] = [];
  await page.route(endpoint, async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    keys.push(route.request().postDataJSON().idempotency_key);
    if (keys.length === 1) {
      const committed = await route.fetch();
      expect(committed.status()).toBe(201);
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Lost creation response after commit" }),
      });
    } else {
      await route.continue();
    }
  });
  await page.getByRole("button", { name: "Create order", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Lost creation response after commit" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Create order", exact: true }).click();
  await expect(page.getByLabel("Quantity for Chicken rice", { exact: true })).toHaveValue("0");
  expect(keys).toHaveLength(2);
  expect(new Set(keys).size).toBe(1);
  const listed = await (await page.request.get(endpoint)).json();
  expect(listed.total).toBe(1);
  const changed = await page.request.post(endpoint, {
    headers: writeHeaders,
    data: {
      idempotency_key: keys[0],
      items: [{ menu_item_id: listed.items[0].items[0].menu_item_id, quantity: 2 }],
    },
  });
  expect(changed.status()).toBe(409);
});
