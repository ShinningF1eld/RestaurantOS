import { test as base, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";

const api = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const origin = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const headers = { Origin: origin, "X-CSRF-Protection": "1" };
type Account = { id: string; email: string; password: string };
const test = base.extend<{ account: Account }>({
  account: async ({}, provideAccount) => {
    const id = randomUUID();
    const account = { id, email: `browser-${id}@example.test`, password: `Browser test ${randomUUID()}` }; // pragma: allowlist secret
    const python = process.env.PLAYWRIGHT_PYTHON ?? path.resolve("../backend/.venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    const seed = path.resolve("tests/seed-auth.py");
    execFileSync(python, [seed, "create", id], { stdio: "pipe", input: JSON.stringify(account), timeout: 20_000 });
    try { await provideAccount(account); }
    finally { execFileSync(python, [seed, "delete", id], { stdio: "pipe", timeout: 20_000 }); }
  },
});

async function signIn(page: Page, account: Account, next = "/dashboard/restaurants") {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Email", { exact: true }).fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new URL(next, origin).href);
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
  await expect(page.getByText(account.email, { exact: true })).toBeVisible();
}

async function expireAccess(page: Page) {
  await page.context().clearCookies({ name: "ros_access" });
}

async function createCatalog(page: Page) {
  const restaurant = await page.request.post(`${api}/api/restaurants`, { headers, data: { name: `Browser ${randomUUID()}`, address: "Test street", phone: "123456789" } });
  expect(restaurant.status()).toBe(201);
  const restaurantId = (await restaurant.json()).id;
  const menu = await page.request.post(`${api}/restaurants/${restaurantId}/menus`, { headers, data: { name: "Browser dinner" } });
  expect(menu.ok()).toBeTruthy();
  const menuId = (await menu.json()).menu_id;
  const item = await page.request.post(`${api}/menus/${menuId}/items`, { headers, data: { name: "Browser noodles", price: "12.50" } });
  expect(item.ok()).toBeTruthy();
  return { restaurantId, menuId };
}

test("anonymous deep link returns to sign in and login survives reload", async ({ page, account }) => {
  await page.goto("/dashboard/restaurants");
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await signIn(page, account);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Restaurants", exact: true })).toBeVisible();
  await expect(page.getByText(account.email, { exact: true })).toBeVisible();
  const cookies = await page.context().cookies();
  for (const name of ["ros_access", "ros_refresh"]) {
    const cookie = cookies.find(value => value.name === name)!;
    expect(cookie.httpOnly).toBeTruthy();
    expect(cookie.sameSite).toBe("Lax");
  }
  const storage = await page.evaluate(() => ({ local: JSON.stringify(localStorage), session: JSON.stringify(sessionStorage), html: document.documentElement.outerHTML }));
  for (const cookie of cookies.filter(value => value.name.startsWith("ros_"))) {
    expect(storage.local).not.toContain(cookie.value);
    expect(storage.session).not.toContain(cookie.value);
    expect(storage.html).not.toContain(cookie.value);
  }
});

test("real authenticated menu, order completion and dashboard flow", async ({ page, account }) => {
  await signIn(page, account);
  const { restaurantId } = await createCatalog(page);
  await page.goto(`/restaurants/${restaurantId}/menu`);
  await expect(page.getByText("Browser dinner", { exact: true })).toBeVisible();
  await page.goto(`/restaurants/${restaurantId}/orders`);
  await page.getByLabel("Quantity for Browser noodles").fill("2");
  const created = page.waitForResponse(response => response.url() === `${api}/api/restaurants/${restaurantId}/orders` && response.request().method() === "POST");
  await page.getByRole("button", { name: "Create order", exact: true }).click();
  expect((await created).status()).toBe(201);
  for (const status of ["submitted", "accepted", "preparing", "ready", "completed"]) {
    const updated = page.waitForResponse(response => response.url().includes("/api/orders/") && response.request().method() === "PUT");
    await page.getByRole("button", { name: `Mark ${status}`, exact: true }).click();
    expect((await updated).ok()).toBeTruthy();
    if (status !== "completed") await expect(page.getByRole("button", { name: `Mark ${["accepted", "preparing", "ready", "completed"][["submitted", "accepted", "preparing", "ready"].indexOf(status)]}`, exact: true })).toBeVisible();
  }
  await page.goto(`/restaurants/${restaurantId}/dashboard`);
  await expect(page.getByText("฿25", { exact: true }).first()).toBeVisible();
  const totals = await (await page.request.get(`${api}/api/restaurants/${restaurantId}/analytics/dashboard`)).json();
  expect(Number(totals.sales.value)).toBe(25);
  expect(totals.orders.value).toBe(1);
});

test("expired SSR access renews once and restores the deep link", async ({ page, account }) => {
  await signIn(page, account);
  const { restaurantId } = await createCatalog(page);
  const oldRefresh = (await page.context().cookies()).find(cookie => cookie.name === "ros_refresh")!.value;
  await expireAccess(page);
  let refreshes = 0;
  page.on("request", request => { if (request.url() === `${api}/auth/refresh`) refreshes++; });
  await page.goto(`/restaurants/${restaurantId}/orders`);
  await expect(page).toHaveURL(new URL(`/restaurants/${restaurantId}/orders`, origin).href);
  await expect(page.getByRole("heading", { name: "New order", exact: true })).toBeVisible();
  expect(refreshes).toBe(1);
  expect((await page.context().cookies()).find(cookie => cookie.name === "ros_refresh")!.value).not.toBe(oldRefresh);
});

test("simultaneous requests and tabs rotate the shared token once", async ({ page, context, account }) => {
  await signIn(page, account);
  const second = await context.newPage();
  await second.goto("/dashboard/restaurants");
  await expect(second.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
  await expireAccess(page);
  let refreshes = 0;
  context.on("request", request => { if (request.url() === `${api}/auth/refresh`) refreshes++; });
  await Promise.all([page.reload(), second.reload()]);
  await expect(page.getByText(account.email, { exact: true })).toBeVisible();
  await expect(second.getByText(account.email, { exact: true })).toBeVisible();
  expect(refreshes).toBe(1);
  expect((await page.request.get(`${api}/auth/me`)).status()).toBe(200);
});

test("logout revokes backend credentials and signs out another tab", async ({ page, context, account }) => {
  await signIn(page, account);
  const second = await context.newPage();
  await second.goto("/dashboard/restaurants");
  await expect(second.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(second).toHaveURL(/\/login(?:\?|$)/);
  expect((await page.request.get(`${api}/auth/me`)).status()).toBe(401);
});

test("refresh failure returns to login without a retry loop", async ({ page, account }) => {
  await signIn(page, account);
  await page.context().clearCookies();
  let refreshes = 0;
  page.on("request", request => { if (request.url() === `${api}/auth/refresh`) refreshes++; });
  await page.reload();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  expect(refreshes).toBe(1);
});

test("failed logout leaves the active session visible", async ({ page, account }) => {
  await signIn(page, account);
  await page.route(`${api}/auth/logout`, route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Unavailable" }) }));
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Sign out failed." })).toHaveText("Sign out failed. Please try again.");
  await expect(page).toHaveURL(new URL("/dashboard/restaurants", origin).href);
  expect((await page.request.get(`${api}/auth/me`)).status()).toBe(200);
});

test("ambiguous failed business write is never automatically retried", async ({ page, account }) => {
  await signIn(page, account);
  let writes = 0;
  await page.route(`${api}/api/restaurants`, async route => {
    if (route.request().method() === "POST") {
      writes++;
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Unavailable" }) });
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Add restaurant", exact: true }).click();
  await page.getByPlaceholder("Restaurant name ", { exact: true }).fill("Uncertain write");
  await page.getByPlaceholder("Restaurant address").fill("Test street");
  await page.getByPlaceholder("Phone number").fill("123456789");
  await page.getByRole("button", { name: "Create Restaurant", exact: true }).click();
  await expect(page.getByText("Failed to create restaurant", { exact: true })).toBeVisible();
  expect(writes).toBe(1);
});

test("login rejects external return destinations", async ({ page, account }) => {
  await page.goto("/login?next=https%3A%2F%2Fevil.example%2F");
  await page.getByLabel("Email", { exact: true }).fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new URL("/dashboard/restaurants", origin).href);
});


test("browser without cross-tab locks safely requires a fresh login", async ({ page, account }) => {
  await signIn(page, account);
  await page.context().addInitScript(() => Object.defineProperty(navigator, "locks", { value: undefined, configurable: true }));
  await expireAccess(page);
  let refreshes = 0;
  page.on("request", request => { if (request.url() === `${api}/auth/refresh`) refreshes++; });
  await page.reload();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  expect(refreshes).toBe(0);
});

test("backend outage stays distinct from an expired identity", async ({ page, account }) => {
  await signIn(page, account);
  await page.route(`${api}/**`, route => route.abort("connectionrefused"));
  await page.reload();
  await expect(page.getByText("Failed to load restaurants", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(new URL("/dashboard/restaurants", origin).href);
});

test("successful renewal retries one rejected business write exactly once", async ({ page, account }) => {
  await signIn(page, account);
  await expireAccess(page);
  let writes = 0;
  let refreshes = 0;
  let navigations = 0;
  page.on("framenavigated", frame => { if (frame === page.mainFrame()) navigations++; });
  page.on("request", request => {
    if (request.url() === `${api}/api/restaurants` && request.method() === "POST") writes++;
    if (request.url() === `${api}/auth/refresh`) refreshes++;
  });
  await page.getByRole("button", { name: "Add restaurant", exact: true }).click();
  const name = `Renewed browser write ${randomUUID()}`;
  await page.getByPlaceholder("Restaurant name ", { exact: true }).fill(name);
  await page.getByPlaceholder("Restaurant address").fill("Test street");
  await page.getByPlaceholder("Phone number").fill("123456789");
  await page.getByRole("button", { name: "Create Restaurant", exact: true }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  expect(writes).toBe(2);
  expect(refreshes).toBe(1);
  expect(navigations).toBe(0);
  const restaurants = await (await page.request.get(`${api}/api/restaurants`)).json();
  expect(restaurants.filter((restaurant: { name: string }) => restaurant.name === name)).toHaveLength(1);
});


test("employee kitchen controls reflect live permissions and the API rejects mixed writes", async ({ page, account }) => {
  await signIn(page, account);
  const { restaurantId, menuId } = await createCatalog(page);
  const items = await (await page.request.get(`${api}/menus/${menuId}/items`)).json();
  const created = await page.request.post(`${api}/api/restaurants/${restaurantId}/orders`, { headers,
    data: { idempotency_key: randomUUID(), items: [{ menu_item_id: items[0].menu_item_id, quantity: 1 }] } });
  expect(created.status()).toBe(201);
  const orderId = (await created.json()).order_id;
  for (const status of ["SUBMITTED", "ACCEPTED"]) {
    expect((await page.request.put(`${api}/api/orders/${orderId}`, { headers, data: { status } })).ok()).toBeTruthy();
  }
  const python = process.env.PLAYWRIGHT_PYTHON ?? path.resolve("../backend/.venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  execFileSync(python, [path.resolve("tests/seed-auth.py"), "employee", account.id, String(restaurantId)], { stdio: "pipe", timeout: 20_000 });
  await page.goto(`/restaurants/${restaurantId}/orders`);
  await expect(page.getByRole("heading", { name: "New order", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Dashboard", exact: true })).toHaveCount(0);
  const forbidden = await page.request.put(`${api}/api/orders/${orderId}`, { headers, data: { status: "PREPARING", payment_status: null } });
  expect(forbidden.status()).toBe(403);
  for (const status of ["preparing", "ready"]) {
    const update = page.waitForResponse(response => response.url().endsWith(`/api/orders/${orderId}`) && response.request().method() === "PUT");
    await page.getByRole("button", { name: `Mark ${status}`, exact: true }).click();
    expect((await update).status()).toBe(200);
  }
  await expect(page.getByRole("button", { name: "Mark completed", exact: true })).toHaveCount(0);
  await page.goto(`/restaurants/${restaurantId}/menu/${menuId}`);
  await expect(page.getByRole("button", { name: "Add menu item", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
  expect((await page.request.put(`${api}/menu-items/${items[0].menu_item_id}`, { headers, data: { price: "99" } })).status()).toBe(403);
  await page.goto(`/restaurants/${restaurantId}/dashboard`);
  await expect(page).toHaveURL(new URL(`/restaurants/${restaurantId}/orders`, origin).href);
});

test("inventory retries committed writes with the same idempotency key", async ({ page, account }) => {
  await signIn(page, account);
  const { restaurantId } = await createCatalog(page);
  await page.goto(`/restaurants/${restaurantId}/inventory`);
  await expect(page.getByRole("heading", { name: "Inventory", exact: true })).toBeVisible();

  const name = `Browser ingredient ${randomUUID()}`;
  await page.getByRole("button", { name: "Add ingredient", exact: true }).click();
  await page.getByLabel("Ingredient name", { exact: true }).fill(name);
  await page.getByLabel("Reorder threshold", { exact: true }).fill("2");
  await page.getByLabel("Opening stock", { exact: true }).fill("2");
  const ingredientUrl = `${api}/api/restaurants/${restaurantId}/inventory/ingredients`;
  const createKeys: string[] = [];
  let createAttempts = 0;
  let ingredientId = 0;
  await page.route(ingredientUrl, async route => {
    if (route.request().method() === "POST") {
      createAttempts++;
      createKeys.push(route.request().postDataJSON().idempotency_key);
      if (createAttempts === 1) {
        const committed = await route.fetch();
        expect(committed.status()).toBe(201);
        ingredientId = (await committed.json()).id;
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Simulated lost response after commit." }),
        });
        return;
      }
    }
    await route.continue();
  });
  await page.getByRole("button", { name: "Save ingredient", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Simulated lost response after commit." }))
    .toContainText("Simulated lost response after commit.");
  await page.getByRole("button", { name: "Save ingredient", exact: true }).click();
  const row = page.getByTestId(`ingredient-row-${ingredientId}`);
  await expect(row).toContainText("2.000 g");
  expect(createAttempts).toBe(2);
  expect(new Set(createKeys).size).toBe(1);
  const listed = await (await page.request.get(ingredientUrl)).json();
  expect(listed.filter((item: { name: string }) => item.name === name)).toHaveLength(1);

  await page.getByRole("button", { name: `Manage stock for ${name}`, exact: true }).click();
  await page.getByLabel("Quantity (g)", { exact: true }).fill("0.500");
  await page.getByLabel("Reason", { exact: true }).fill("Browser receipt retry");
  const movementUrl = `${ingredientUrl}/${ingredientId}/movements`;
  const stockKeys: string[] = [];
  let stockAttempts = 0;
  let movementId = 0;
  await page.route(movementUrl, async route => {
    if (route.request().method() === "POST") {
      stockAttempts++;
      stockKeys.push(route.request().postDataJSON().idempotency_key);
      if (stockAttempts === 1) {
        const committed = await route.fetch();
        expect(committed.status()).toBe(201);
        movementId = (await committed.json()).id;
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Simulated lost response after commit." }),
        });
        return;
      }
    }
    await route.continue();
  });
  await page.getByRole("button", { name: "Record stock", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Simulated lost response after commit." }))
    .toContainText("Simulated lost response after commit.");
  await page.getByRole("button", { name: "Record stock", exact: true }).click();
  await expect(row).toContainText("2.500 g");
  expect(stockAttempts).toBe(2);
  expect(new Set(stockKeys).size).toBe(1);

  await page.getByRole("button", { name: `History for ${name}`, exact: true }).click();
  await expect(page.getByRole("region", { name: "Stock history" })).toContainText("Browser receipt retry");
  await expect(page.getByRole("region", { name: "Stock history" })).toContainText(account.email);
  const history = await (await page.request.get(movementUrl)).json();
  expect(history.filter((movement: { id: number }) => movement.id === movementId)).toHaveLength(1);
  expect(history).toHaveLength(2);
});

test("inventory row actions expand and close history and edit beneath their ingredient", async ({ page, account }, testInfo) => {
  await signIn(page, account);
  const { restaurantId } = await createCatalog(page);
  const ingredientsUrl = `${api}/api/restaurants/${restaurantId}/inventory/ingredients`;
  const firstResponse = await page.request.post(ingredientsUrl, {
    headers,
    data: {
      name: `Rice ${randomUUID().slice(0, 8)}`,
      unit: "g",
      reorder_threshold: "0",
      opening_quantity: "2",
      idempotency_key: `history-source-${randomUUID()}`,
    },
  });
  expect(firstResponse.status()).toBe(201);
  const first = await firstResponse.json();
  const secondResponse = await page.request.post(ingredientsUrl, {
    headers,
    data: {
      name: `Bottles ${randomUUID().slice(0, 8)}`,
      unit: "piece",
      reorder_threshold: "0",
      opening_quantity: "7",
      idempotency_key: `history-target-${randomUUID()}`,
    },
  });
  expect(secondResponse.status()).toBe(201);
  const second = await secondResponse.json();

  await page.goto(`/restaurants/${restaurantId}/inventory`);
  const region = page.getByRole("region", { name: "Stock history" });
  const firstHistoryButton = page.getByRole("button", { name: `History for ${first.name}`, exact: true });
  await firstHistoryButton.click();
  await expect(firstHistoryButton).toHaveAttribute("aria-expanded", "true");
  const firstDetails = page.getByTestId(`ingredient-details-${first.id}`);
  await expect(firstDetails).toBeVisible();
  expect(await firstDetails.evaluate(element => element.tagName)).toBe("TR");
  await expect(region).toContainText("2.000 g");
  await page.screenshot({ path: testInfo.outputPath("inventory-history-expanded.png"), fullPage: true });

  await region.getByRole("button", { name: `Close history for ${first.name}`, exact: true }).click();
  await expect(firstHistoryButton).toHaveAttribute("aria-expanded", "false");
  await expect(firstDetails).toHaveCount(0);

  await firstHistoryButton.click();
  await expect(region).toContainText("2.000 g");
  const secondHistoryUrl = `${api}/api/restaurants/${restaurantId}/inventory/ingredients/${second.id}/movements?limit=20&offset=0`;
  await page.route(url => url.href === secondHistoryUrl, route => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "History temporarily unavailable." }),
  }));
  await page.getByRole("button", { name: `History for ${second.name}`, exact: true }).click();
  await expect(region.getByRole("heading", { name: `Stock history: ${second.name}`, exact: true })).toBeVisible();
  await expect(region.getByRole("alert")).toHaveText("History temporarily unavailable.");
  await expect(region.getByText("No movements on this page.", { exact: true })).toBeVisible();
  await expect(region).not.toContainText("2.000 piece");

  const secondHistoryButton = page.getByRole("button", { name: `History for ${second.name}`, exact: true });
  await region.getByRole("button", { name: `Close history for ${second.name}`, exact: true }).click();
  await expect(secondHistoryButton).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId(`ingredient-details-${second.id}`)).toHaveCount(0);

  const editButton = page.getByRole("button", { name: `Edit ${first.name}`, exact: true });
  await editButton.click();
  await expect(editButton).toHaveAttribute("aria-expanded", "true");
  const editDetails = page.getByTestId(`ingredient-details-${first.id}`);
  await expect(editDetails).toBeVisible();
  expect(await editDetails.evaluate(element => element.tagName)).toBe("TR");
  const editForm = editDetails.getByRole("form", { name: `Edit ingredient ${first.name}`, exact: true });
  await expect(editForm).toBeVisible();
  expect(await editForm.evaluate(form => form.closest("tr")?.getAttribute("data-testid")))
    .toBe(`ingredient-details-${first.id}`);
  await expect(editDetails.getByRole("heading", { name: "Edit ingredient", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("inventory-expanded.png"), fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({ path: testInfo.outputPath("inventory-expanded-mobile.png"), fullPage: true });
  const documentWidths = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(documentWidths.page).toBeLessThanOrEqual(documentWidths.viewport);
  await page.getByRole("button", { name: `Close edit for ${first.name}`, exact: true }).click();
  await expect(editButton).toHaveAttribute("aria-expanded", "false");
  await expect(editDetails).toHaveCount(0);
});

test("inventory owner workflow edits, records waste, refreshes stale counts, archives and restores", async ({ page, account }) => {
  await signIn(page, account);
  const { restaurantId } = await createCatalog(page);
  await page.goto(`/restaurants/${restaurantId}/inventory`);
  const name = `Count workflow ${randomUUID()}`;
  const listUrl = `${api}/api/restaurants/${restaurantId}/inventory/ingredients`;

  await page.getByRole("button", { name: "Add ingredient", exact: true }).click();
  await page.getByLabel("Ingredient name", { exact: true }).fill(name);
  await page.getByLabel("Reorder threshold", { exact: true }).fill("2");
  await page.getByLabel("Opening stock", { exact: true }).fill("5");
  const creationResponse = page.waitForResponse(response =>
    response.url() === listUrl
    && response.request().method() === "POST"
    && response.status() === 201,
  );
  await page.getByRole("button", { name: "Save ingredient", exact: true }).click();
  await creationResponse;
  const created = (await (await page.request.get(listUrl)).json()).find(
    (ingredient: { name: string }) => ingredient.name === name,
  );
  expect(created).toBeTruthy();
  const row = page.getByTestId(`ingredient-row-${created.id}`);
  await expect(row).toContainText("5.000 g");

  await page.getByRole("button", { name: `Edit ${name}`, exact: true }).click();
  await page.getByLabel("Reorder threshold", { exact: true }).fill("4");
  await page.getByRole("button", { name: "Save ingredient", exact: true }).click();
  await expect(row).toContainText("Healthy");

  await page.getByRole("button", { name: `Manage stock for ${name}`, exact: true }).click();
  await page.getByRole("combobox", { name: "Stock action", exact: true }).selectOption("waste");
  await page.getByLabel("Quantity (g)", { exact: true }).fill("1");
  await page.getByLabel("Reason", { exact: true }).fill("Damaged package");
  await page.getByRole("button", { name: "Record stock", exact: true }).click();
  await expect(row).toContainText("4.000 g");

  await page.getByRole("button", { name: `Manage stock for ${name}`, exact: true }).click();
  await page.getByRole("combobox", { name: "Stock action", exact: true }).selectOption("count");
  await page.getByLabel("Counted quantity (g)", { exact: true }).fill("4");
  await page.getByLabel("Reason", { exact: true }).fill("Shelf count");
  const item = (await (await page.request.get(listUrl)).json()).find(
    (ingredient: { name: string }) => ingredient.name === name,
  );
  expect(item).toBeTruthy();
  const externalReceipt = await page.request.post(`${listUrl}/${item.id}/movements`, {
    headers,
    data: {
      kind: "receipt",
      quantity: "2",
      reason: "Delivery during count",
      expected_version: null,
      idempotency_key: `browser-race-${randomUUID()}`,
    },
  });
  expect(externalReceipt.status()).toBe(201);
  await page.getByRole("button", { name: "Record stock", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Stock changed since this count began" }))
    .toContainText("Stock changed since this count began");
  await page.getByRole("button", { name: "Refresh count", exact: true }).click();
  await expect(page.getByRole("heading", { name: `Manage stock: ${name}`, exact: true })).toBeVisible();
  await expect(page.getByText("On hand: 6.000 g.")).toBeVisible();
  await page.getByLabel("Counted quantity (g)", { exact: true }).fill("6");
  await page.getByRole("button", { name: "Record stock", exact: true }).click();
  await expect(row).toContainText("6.000 g");

  await page.getByRole("button", { name: `Archive ${name}`, exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Record remaining stock as waste or count it to zero" }))
    .toContainText("Record remaining stock as waste or count it to zero");
  await page.getByRole("button", { name: `Manage stock for ${name}`, exact: true }).click();
  await page.getByRole("combobox", { name: "Stock action", exact: true }).selectOption("waste");
  await page.getByLabel("Quantity (g)", { exact: true }).fill("6");
  await page.getByLabel("Reason", { exact: true }).fill("Clear remaining stock");
  await page.getByRole("button", { name: "Record stock", exact: true }).click();
  await expect(row).toContainText("0.000 g");
  await page.getByRole("button", { name: `Archive ${name}`, exact: true }).click();
  await expect(row).toContainText("Archived");
  await page.getByRole("button", { name: `Restore ${name}`, exact: true }).click();
  await expect(row).toContainText("Low stock");
});

test("employee cannot see or call inventory operations", async ({ page, account }) => {
  await signIn(page, account);
  const { restaurantId } = await createCatalog(page);
  const listUrl = `${api}/api/restaurants/${restaurantId}/inventory/ingredients`;
  const created = await page.request.post(listUrl, {
    headers,
    data: {
      name: "Restricted ingredient",
      unit: "g",
      reorder_threshold: "0",
      opening_quantity: "0",
      idempotency_key: "owner-opening",
    },
  });
  expect(created.status()).toBe(201);
  const ingredientId = (await created.json()).id;
  const python = process.env.PLAYWRIGHT_PYTHON ?? path.resolve("../backend/.venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  execFileSync(python, [path.resolve("tests/seed-auth.py"), "employee", account.id, String(restaurantId)], { stdio: "pipe", timeout: 20_000 });

  await page.goto(`/restaurants/${restaurantId}/inventory`);
  await expect(page.getByRole("link", { name: "Inventory", exact: true })).toHaveCount(0);
  await expect(page.getByRole("alert").filter({ hasText: "Inventory is unavailable for your role." }))
    .toHaveText("Inventory is unavailable for your role.");
  const denied = await Promise.all([
    page.request.get(listUrl),
    page.request.post(listUrl, { headers, data: {
      name: "Forbidden ingredient", unit: "g", reorder_threshold: "0",
      opening_quantity: "0", idempotency_key: "employee-create",
    } }),
    page.request.put(`${listUrl}/${ingredientId}`, { headers, data: {
      name: "Restricted ingredient", unit: "g", reorder_threshold: "0", is_active: true,
    } }),
    page.request.post(`${listUrl}/${ingredientId}/movements`, { headers, data: {
      kind: "receipt", quantity: "1", reason: "Forbidden", expected_version: null,
      idempotency_key: "employee-stock",
    } }),
    page.request.get(`${listUrl}/${ingredientId}/movements`),
  ]);
  expect(denied.map(response => response.status())).toEqual([403, 403, 403, 403, 403]);
});
