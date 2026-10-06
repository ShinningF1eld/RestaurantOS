import { test as base, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { randomUUID } from "node:crypto";

export const api = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const origin = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
export const writeHeaders = { Origin: origin, "X-CSRF-Protection": "1" };
type Account = { id: string; email: string; password: string };
export const test = base.extend<{ account: Account }>({
  account: async ({}, provide) => {
    const id = randomUUID();
    const account = {
      id,
      email: `browser-${id}@example.test`,
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
      input: JSON.stringify(account),
      stdio: "pipe",
      timeout: 20_000,
    });
    try {
      await provide(account);
    } finally {
      execFileSync(python, [seed, "delete", id], { stdio: "pipe", timeout: 20_000 });
    }
  },
});
export { expect };

export async function signIn(page: Page, account: Account) {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
}

export async function catalog(page: Page) {
  const restaurantResponse = await page.request.post(`${api}/api/restaurants`, {
    headers: writeHeaders,
    data: { name: `Recipe branch ${randomUUID()}` },
  });
  expect(restaurantResponse.ok()).toBeTruthy();
  const restaurantId = (await restaurantResponse.json()).id;
  const menuResponse = await page.request.post(`${api}/restaurants/${restaurantId}/menus`, {
    headers: writeHeaders,
    data: { name: "Dinner" },
  });
  expect(menuResponse.ok()).toBeTruthy();
  const menuId = (await menuResponse.json()).menu_id;
  const itemResponse = await page.request.post(`${api}/menus/${menuId}/items`, {
    headers: writeHeaders,
    data: { name: "Chicken rice", price: "12.50" },
  });
  expect(itemResponse.ok()).toBeTruthy();
  const menuItemId = (await itemResponse.json()).menu_item_id;
  return { restaurantId, menuId, menuItemId };
}

export async function ingredient(page: Page, restaurantId: number, name: string, amount: string) {
  const response = await page.request.post(
    `${api}/api/restaurants/${restaurantId}/inventory/ingredients`,
    {
      headers: writeHeaders,
      data: {
        name,
        unit: "g",
        reorder_threshold: "100",
        opening_quantity: amount,
        idempotency_key: randomUUID(),
      },
    },
  );
  expect(response.ok()).toBeTruthy();
  return response.json();
}
