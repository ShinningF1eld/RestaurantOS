import { execFileSync } from "node:child_process";
import path from "node:path";
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

function cacheSnapshot(restaurantId: number, menuId: number) {
  const python = process.env.PLAYWRIGHT_PYTHON;
  if (!python) throw new Error("Run the isolated browser harness");
  return JSON.parse(
    execFileSync(
      python,
      [path.resolve("tests/milestone7-support.py"), String(restaurantId), String(menuId)],
      {
        stdio: "pipe",
        timeout: 20_000,
      },
    ).toString(),
  ) as ({ source_started_at: number; items?: { price: string }[] } | null)[];
}

function redisCommand(...arguments_: string[]) {
  const container = process.env.PLAYWRIGHT_REDIS_CONTAINER;
  if (!container || !/^restaurantos-auth-outage-[a-f0-9]{12}$/.test(container)) {
    throw new Error("Explicit browser-owned Redis container required");
  }
  return execFileSync("docker", [...arguments_, container], { stdio: "pipe", timeout: 45_000 })
    .toString()
    .trim();
}

test("warm catalog hits retain live stock and committed menu/item updates reach Chromium", async ({
  page,
  account,
}) => {
  await signIn(page, account);
  const { restaurantId, menuId, menuItemId } = await catalog(page);
  const stock = await ingredient(page, restaurantId, "Warm cache rice", "20");
  expect(
    (
      await page.request.put(`${api}/menu-items/${menuItemId}/recipe`, {
        headers: writeHeaders,
        data: {
          inventory_tracking: true,
          components: [{ ingredient_id: stock.id, quantity: "4" }],
        },
      })
    ).ok(),
  ).toBeTruthy();
  // Real browser fetches share HttpOnly cookies with the rendered application.
  const read = () =>
    page.evaluate(
      async ({ api, restaurantId, menuId }) => {
        const menus = await fetch(`${api}/restaurants/${restaurantId}/menus`, {
          credentials: "include",
        });
        const items = await fetch(`${api}/menus/${menuId}/items`, { credentials: "include" });
        if (!menus.ok || !items.ok) throw new Error("Catalog read failed");
        return { menus: await menus.json(), items: await items.json() };
      },
      { api, restaurantId, menuId },
    );
  expect((await read()).items[0].available_portions).toBe(5);
  const filled = cacheSnapshot(restaurantId, menuId);
  expect(filled.every(Boolean)).toBe(true);
  await read();
  expect(cacheSnapshot(restaurantId, menuId)).toEqual(filled);
  expect(
    (
      await page.request.post(
        `${api}/api/restaurants/${restaurantId}/inventory/ingredients/${stock.id}/movements`,
        {
          headers: writeHeaders,
          data: {
            kind: "waste",
            quantity: "20",
            reason: "Browser stock freshness",
            idempotency_key: randomUUID(),
          },
        },
      )
    ).status(),
  ).toBe(201);
  const afterWaste = await read();
  expect(afterWaste.items[0].out_of_stock).toBe(true);
  expect(afterWaste.items[0].available_portions).toBe(0);
  expect(cacheSnapshot(restaurantId, menuId)).toEqual(filled);
  await page.goto(`/restaurants/${restaurantId}/orders`);
  await expect(page.getByLabel("Quantity for Chicken rice", { exact: true })).toBeDisabled();
  expect(
    (
      await page.request.put(`${api}/menus/${menuId}`, {
        headers: writeHeaders,
        data: { name: "Updated warm menu" },
      })
    ).ok(),
  ).toBeTruthy();
  expect(
    (
      await page.request.put(`${api}/menu-items/${menuItemId}`, {
        headers: writeHeaders,
        data: { name: "Updated warm rice", price: "18.99" },
      })
    ).ok(),
  ).toBeTruthy();
  const updated = await read();
  expect(updated.menus[0].name).toBe("Updated warm menu");
  expect(updated.items[0].name).toBe("Updated warm rice");
  expect(updated.items[0].price).toBe("18.99");
  await page.goto(`/restaurants/${restaurantId}/menu`);
  await expect(page.getByText("Updated warm menu", { exact: true })).toBeVisible();
});

test("login UI throttles normally and Redis outage/recovery preserves sessions and stricter local limits", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  await signIn(page, account);
  const { restaurantId, menuId } = await catalog(page);
  // Keep the real fixed-window test away from its minute boundary.
  await expect
    .poll(() => Date.now() % 60_000, { timeout: 65_000, intervals: [1000] })
    .toBeLessThan(15_000);
  await page.request.get(`${api}/restaurants/${restaurantId}/menus`);
  await page.request.get(`${api}/menus/${menuId}/items`);
  expect(cacheSnapshot(restaurantId, menuId).every(Boolean)).toBe(true);
  // A separate page retains the original authenticated session throughout.
  const sessionPage = await page.context().newPage();
  const failedEmail = `failed-${randomUUID()}@example.test`;
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(failedEmail);
  await page.getByLabel("Password", { exact: true }).fill(`Browser test ${randomUUID()}`);
  const attempt = async () => {
    const response = page.waitForResponse(
      (r) => r.url() === `${api}/auth/login` && r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    const result = await response;
    await expect(page.locator("form").getByRole("alert")).toHaveText((await result.json()).detail);
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeEnabled();
    return result;
  };
  for (let index = 0; index < 5; index++) expect((await attempt()).status()).toBe(401);
  const normalThrottle = await attempt();
  expect(normalThrottle.status()).toBe(429);
  expect(Number(normalThrottle.headers()["retry-after"])).toBeGreaterThan(0);
  const genericBody = await normalThrottle.json();
  try {
    redisCommand("stop", "--time", "0");
    for (let index = 0; index < 3; index++) expect((await attempt()).status()).toBe(401);
    const localThrottle = await attempt();
    expect(localThrottle.status()).toBe(429);
    expect(await localThrottle.json()).toEqual(genericBody);
    // Both scoped list reads and SSR continue through PostgreSQL during loss.
    await sessionPage.goto(`/restaurants/${restaurantId}/orders`);
    await expect(
      sessionPage.getByLabel("Quantity for Chicken rice", { exact: true }),
    ).toBeEnabled();
    expect((await sessionPage.request.get(`${api}/auth/me`)).status()).toBe(200);
    expect(
      (await sessionPage.request.post(`${api}/auth/refresh`, { headers: writeHeaders })).status(),
    ).toBe(200);
    redisCommand("start");
    // The real five-second cooldown and three real limiter probes are retained.
    // Successful login produces no failure counts; polling awaits actual recovery.
    await expect
      .poll(
        async () => {
          const result = await sessionPage.request.post(`${api}/auth/login`, {
            headers: writeHeaders,
            data: { email: account.email, password: account.password },
          });
          expect(result.status()).toBe(200);
          const events = JSON.parse(
            execFileSync(
              process.env.PLAYWRIGHT_PYTHON!,
              [path.resolve("tests/milestone7-support.py"), "limiter"],
              { stdio: "pipe", timeout: 20_000 },
            ).toString(),
          ) as string[];
          return events.at(-1);
        },
        { timeout: 35_000, intervals: [5100] },
      )
      .toBe("auth_limiter_healthy");
    await expect
      .poll(
        async () => {
          await sessionPage.request.get(`${api}/restaurants/${restaurantId}/menus`);
          await sessionPage.request.get(`${api}/menus/${menuId}/items`);
          return cacheSnapshot(restaurantId, menuId).every(Boolean);
        },
        { timeout: 20_000, intervals: [1000] },
      )
      .toBe(true);
    // Surviving local failures remain enforced when Redis returns.
    expect((await attempt()).status()).toBe(429);
    await sessionPage.reload();
    await expect(sessionPage.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
  } finally {
    redisCommand("start");
    await sessionPage.close();
  }
});
