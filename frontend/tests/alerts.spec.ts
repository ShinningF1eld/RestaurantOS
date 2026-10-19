import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";
import {
  test,
  expect,
  signIn,
  catalog,
  ingredient,
  api,
  writeHeaders,
} from "./milestone5-fixtures";

// Projection correctness permits the worker's 60s pending/stall recovery plus
// relay/processing time. The separate freshness benchmark retains its 5s target.
const workerProjectionWaitMs = 90_000;

test("inventory alerts show real worker history, retain forms and recover from refresh failure", async ({
  page,
  account,
}) => {
  test.setTimeout(60_000 + 2 * workerProjectionWaitMs);
  await signIn(page, account);
  const { restaurantId } = await catalog(page);
  const stock = await ingredient(page, restaurantId, "Alert rice", "2");
  const url = `${api}/api/restaurants/${restaurantId}/inventory/alerts`;
  await expect
    .poll(async () => (await (await page.request.get(url)).json()).total, {
      timeout: workerProjectionWaitMs,
    })
    .toBe(1);
  await page.goto(`/restaurants/${restaurantId}/inventory`);
  const alerts = page.getByRole("region", { name: "Inventory alerts" });
  await expect(alerts).toContainText("Alert rice");
  await page.getByRole("button", { name: "Manage stock for Alert rice", exact: true }).click();
  const form = page.getByRole("form", { name: "Manage stock form for Alert rice" });
  await form.getByLabel("Reason").fill("Keep this draft");
  await form.getByLabel("Quantity (g)", { exact: true }).fill("3");
  await form.getByLabel("Reason").focus();
  await page.clock.install();
  await page.clock.fastForward(15_000);
  await expect(form.getByLabel("Reason")).toBeFocused();
  await expect(form.getByLabel("Reason")).toHaveValue("Keep this draft");
  await page.route(url + "?**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Refresh unavailable" }),
    }),
  );
  await alerts.getByRole("button", { name: "Refresh alerts", exact: true }).click();
  await expect(alerts.getByRole("alert")).toContainText("Last-known data");
  await expect(alerts).toContainText("Alert rice");
  await page.unroute(url + "?**");
  await alerts.getByRole("button", { name: "Retry alerts", exact: true }).click();
  await expect(alerts.getByRole("alert")).toHaveCount(0);
  // A successful local replenishment refreshes immediately, even before the worker catches up.
  await form.getByRole("button", { name: "Record stock", exact: true }).click();
  await expect(alerts).toContainText("5.000 g");
  // 2 + 3 remains low against threshold 100. Recover using the real API, then refresh.
  const receipt = await page.request.post(
    `${api}/api/restaurants/${restaurantId}/inventory/ingredients/${stock.id}/movements`,
    {
      headers: writeHeaders,
      data: {
        kind: "receipt",
        quantity: "200",
        reason: "Recover stock",
        idempotency_key: randomUUID(),
      },
    },
  );
  expect(receipt.status()).toBe(201);
  await alerts.getByRole("button", { name: "Refresh alerts", exact: true }).click();
  await expect(alerts).toContainText("No active alerts");
  await expect
    .poll(
      async () =>
        (await (await page.request.get(url + "/history")).json()).items[0].resolution_reason,
      { timeout: workerProjectionWaitMs },
    )
    .toBe("stock_recovered");
  await alerts.getByRole("button", { name: "Alert history", exact: true }).click();
  await expect(alerts).toContainText("Opening 2.000 g");
  await expect(alerts).toContainText("Stock recovered");
});

test("inventory alerts clear protected data when the current role loses access", async ({
  page,
  account,
}) => {
  test.setTimeout(60_000 + workerProjectionWaitMs);
  await signIn(page, account);
  const { restaurantId } = await catalog(page);
  await ingredient(page, restaurantId, "Private alert", "1");
  const url = `${api}/api/restaurants/${restaurantId}/inventory/alerts`;
  await expect
    .poll(async () => (await (await page.request.get(url)).json()).total, {
      timeout: workerProjectionWaitMs,
    })
    .toBe(1);
  await page.goto(`/restaurants/${restaurantId}/inventory`);
  const alerts = page.getByRole("region", { name: "Inventory alerts" });
  await expect(alerts).toContainText("Private alert");
  const python = process.env.PLAYWRIGHT_PYTHON;
  if (!python) throw new Error("Run the isolated browser harness");
  execFileSync(
    python,
    [path.resolve("tests/seed-auth.py"), "employee", account.id, String(restaurantId)],
    { stdio: "pipe", timeout: 20_000 },
  );
  await alerts.getByRole("button", { name: "Refresh alerts", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Inventory is unavailable");
  await expect(page.getByText("Private alert", { exact: true })).toHaveCount(0);
  expect((await page.request.get(url + "/history")).status()).toBe(403);
});

test("inventory alert history paginates all ongoing episodes without mixing branches", async ({
  page,
  account,
}) => {
  test.setTimeout(60_000 + workerProjectionWaitMs);
  await signIn(page, account);
  const { restaurantId } = await catalog(page);
  for (let index = 0; index < 21; index++) {
    await ingredient(page, restaurantId, `Episode ${index}`, "1");
  }
  const { restaurantId: otherId } = await catalog(page);
  await ingredient(page, otherId, "Other branch only", "1");
  const url = `${api}/api/restaurants/${restaurantId}/inventory/alerts/history`;
  await expect
    .poll(async () => (await (await page.request.get(url)).json()).total, {
      timeout: workerProjectionWaitMs,
    })
    .toBe(21);
  await page.goto(`/restaurants/${restaurantId}/inventory`);
  await page.getByRole("button", { name: "Alert history", exact: true }).click();
  const history = page.locator("#alert-history");
  await expect(history.getByRole("listitem")).toHaveCount(20);
  await expect(history).not.toContainText("Other branch only");
  await history.getByRole("button", { name: "Next alert history", exact: true }).click();
  await expect(history.getByRole("listitem")).toHaveCount(1);
  await expect(history).toContainText("Episode 0");
  await expect(history).toContainText("Active in recorded history");
  await history.getByRole("button", { name: "Previous alert history", exact: true }).click();
  await expect(history.getByRole("listitem")).toHaveCount(20);
});
