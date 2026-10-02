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
    data: { items: [{ menu_item_id: items[0].menu_item_id, quantity: 1 }] } });
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
