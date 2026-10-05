import { test, expect, signIn, catalog, ingredient, api, writeHeaders } from "./milestone5-fixtures";
import path from "node:path";

test("recipe editor saves multiple fixed-unit ingredients without duplicates and updates stock labels", async ({ page, account }) => {
  await signIn(page, account);
  const { restaurantId, menuId, menuItemId } = await catalog(page);
  await ingredient(page, restaurantId, "Chicken", "150");
  await ingredient(page, restaurantId, "Rice", "50");
  await page.goto(`/restaurants/${restaurantId}/menu/${menuId}`);
  await page.getByRole("button", { name: "Recipe for Chicken rice", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Recipe for Chicken rice", exact: true });
  await expect(dialog.getByText("Loading recipe and ingredients…")).toBeHidden();
  await dialog.getByLabel("Track ingredient stock").check();
  await dialog.getByRole("button", { name: "Add recipe ingredient", exact: true }).click();
  await dialog.getByLabel("Ingredient 1", { exact: true }).selectOption({ label: "Chicken" });
  await expect(dialog.getByText("Quantity (g)", { exact: true })).toBeVisible();
  await dialog.getByLabel("Recipe quantity 1", { exact: true }).fill("150");
  await dialog.getByRole("button", { name: "Add recipe ingredient", exact: true }).click();
  await expect(dialog.getByLabel("Ingredient 2", { exact: true }).locator("option")).toHaveCount(1);
  await dialog.getByLabel("Recipe quantity 2", { exact: true }).fill("100");
  await expect(dialog.getByRole("button", { name: "Add recipe ingredient", exact: true })).toBeDisabled();
  if (process.env.M5_ARTIFACT_DIR) {
    await page.screenshot({ path: path.join(process.env.M5_ARTIFACT_DIR, "recipe-desktop.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(process.env.M5_ARTIFACT_DIR, "recipe-mobile.png") });
    await page.setViewportSize({ width: 1280, height: 800 });
  }
  await dialog.getByRole("button", { name: "Save recipe", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Out of stock", { exact: true })).toBeVisible();
  const response = await page.request.get(`${api}/menu-items/${menuItemId}/recipe`);
  const saved = await response.json();
  expect(saved.inventory_tracking).toBe(true);
  expect(saved.components.map((row: { unit: string }) => row.unit)).toEqual(["g", "g"]);
  await page.getByRole("button", { name: "Recipe for Chicken rice", exact: true }).click();
  await expect(dialog.getByLabel("Recipe quantity 2", { exact: true })).toHaveValue("100.000");
  await dialog.getByLabel("Recipe quantity 2", { exact: true }).fill("50");
  await dialog.getByRole("button", { name: "Save recipe", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Out of stock", { exact: true })).toBeHidden();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Delete Chicken rice", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No menu items yet", exact: true })).toBeVisible();
  expect((await page.request.get(`${api}/menu-items/${menuItemId}/recipe`)).status()).toBe(404);
});

test("recipe editor keeps tracking disabled until a valid recipe is saved", async ({ page, account }) => {
  await signIn(page, account);
  const { restaurantId, menuId, menuItemId } = await catalog(page);
  await page.goto(`/restaurants/${restaurantId}/menu/${menuId}`);
  await page.getByRole("button", { name: "Recipe for Chicken rice", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("No ingredients in this recipe yet.")).toBeVisible();
  await dialog.getByLabel("Track ingredient stock").check();
  await dialog.getByRole("button", { name: "Save recipe", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Add at least one ingredient");
  expect((await (await page.request.get(`${api}/menu-items/${menuItemId}`)).json()).inventory_tracking).toBe(false);
  const invalid = await page.request.put(`${api}/menu-items/${menuItemId}/recipe`, { headers: writeHeaders, data: { inventory_tracking: true, components: [] } });
  expect(invalid.status()).toBe(422);
});
