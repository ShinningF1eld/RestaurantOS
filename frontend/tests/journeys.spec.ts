import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect, signIn, catalog, api, writeHeaders } from "./milestone5-fixtures";

test("assigned manager can create orders but cannot access unassigned branches or owner controls", async ({
  page,
  account,
}) => {
  await signIn(page, account);
  const assigned = await catalog(page);
  const unassigned = await catalog(page);
  const python =
    process.env.PLAYWRIGHT_PYTHON ??
    path.resolve(
      "../backend/.venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    );
  execFileSync(
    python,
    [path.resolve("tests/seed-auth.py"), "manager", account.id, String(assigned.restaurantId)],
    { stdio: "pipe", timeout: 20_000 },
  );
  await page.goto(`/restaurants/${assigned.restaurantId}/orders`);
  await expect(
    page.locator(`a[href="/restaurants/${assigned.restaurantId}/employees"]`),
  ).toHaveCount(0);
  await page.getByLabel("Quantity for Chicken rice", { exact: true }).fill("1");
  await page.getByRole("button", { name: "Create order", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Order #\d+/ })).toHaveCount(1);
  const direct = await page.request.get(`${api}/api/restaurants/${unassigned.restaurantId}/orders`);
  expect(direct.status()).toBe(404);
  const createBranch = await page.request.post(`${api}/api/restaurants`, {
    headers: writeHeaders,
    data: { name: "Forbidden branch" },
  });
  expect(createBranch.status()).toBe(403);
  expect((await page.request.get(`${api}/api/memberships`)).status()).toBe(403);
  await page.goto(`/restaurants/${unassigned.restaurantId}/orders`);
  await expect(page.getByRole("heading", { name: /not found|could not be found/i })).toBeVisible();
});

test("owner selects and switches restaurants without mixing order data", async ({
  page,
  account,
}) => {
  await signIn(page, account);
  const first = await catalog(page);
  const second = await catalog(page);
  const firstName = (
    await (await page.request.get(`${api}/api/restaurants/${first.restaurantId}`)).json()
  ).name;
  const secondName = (
    await (await page.request.get(`${api}/api/restaurants/${second.restaurantId}`)).json()
  ).name;
  const customer = `First branch ${randomUUID()}`;
  const created = await page.request.post(`${api}/api/restaurants/${first.restaurantId}/orders`, {
    headers: writeHeaders,
    data: {
      idempotency_key: randomUUID(),
      customer_name: customer,
      items: [{ menu_item_id: first.menuItemId, quantity: 1 }],
    },
  });
  expect(created.status()).toBe(201);

  await page.goto("/dashboard/restaurants");
  await page.getByRole("heading", { name: firstName, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/restaurants/${first.restaurantId}/dashboard$`));
  await page.getByRole("link", { name: "Orders", exact: true }).click();
  await expect(page.getByText(customer, { exact: true })).toBeVisible();

  await page.locator('a[href="/dashboard/restaurants"]').click();
  await page.getByRole("heading", { name: secondName, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/restaurants/${second.restaurantId}/dashboard$`));
  await page.getByRole("link", { name: "Orders", exact: true }).click();
  await expect(page.getByText(customer, { exact: true })).toHaveCount(0);
  const secondOrders = await page.request.get(
    `${api}/api/restaurants/${second.restaurantId}/orders`,
  );
  expect(secondOrders.ok()).toBeTruthy();
  expect((await secondOrders.json()).items).toHaveLength(0);
});

test("another tenant's restaurant is hidden and rejects direct access", async ({
  page,
  account,
  browser,
}) => {
  await signIn(page, account);
  const branch = await catalog(page);
  const outsider = await browser.newContext();
  try {
    // A separately provisioned tenant is created through the same isolated seed
    // contract; no authentication or tenant dependency is bypassed.
    const outsiderPage = await outsider.newPage();
    const { execFileSync } = await import("node:child_process");
    const path = await import("node:path");
    const id = randomUUID();
    const other = {
      id,
      email: `outsider-${id}@example.test`,
      password: `Browser test ${randomUUID()}`, // pragma: allowlist secret
    };
    const python =
      process.env.PLAYWRIGHT_PYTHON ??
      path.resolve(
        "../backend/.venv",
        process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
      );
    const seed = path.resolve("tests/seed-auth.py");
    execFileSync(python, [seed, "create", id], {
      input: JSON.stringify(other),
      stdio: "pipe",
      timeout: 20_000,
    });
    try {
      await signIn(outsiderPage, other);
      const restaurants = await outsiderPage.request.get(`${api}/api/restaurants`);
      expect(restaurants.ok()).toBeTruthy();
      expect(
        (await restaurants.json()).some((row: { id: number }) => row.id === branch.restaurantId),
      ).toBe(false);
      const direct = await outsiderPage.request.get(
        `${api}/api/restaurants/${branch.restaurantId}`,
      );
      expect(direct.status()).toBe(404);
      const orders = await outsiderPage.request.get(
        `${api}/api/restaurants/${branch.restaurantId}/orders`,
      );
      expect(orders.status()).toBe(404);
      await outsiderPage.goto(`/restaurants/${branch.restaurantId}/orders`);
      await expect(outsiderPage.getByText("Create order", { exact: true })).toHaveCount(0);
      await expect(
        outsiderPage.getByRole("heading", { name: /not found|could not be found/i }),
      ).toBeVisible();
    } finally {
      execFileSync(python, [seed, "delete", id], { stdio: "pipe", timeout: 20_000 });
    }
  } finally {
    await outsider.close();
  }
});
