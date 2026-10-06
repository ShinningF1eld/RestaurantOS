import { apiFetch } from "./client";
import type { Recipe, RecipeUpdate } from "@/types/recipe";

export async function getRecipe(menuItemId: number): Promise<Recipe> {
  return (await apiFetch(`/menu-items/${menuItemId}/recipe`)).json();
}

export async function updateRecipe(menuItemId: number, data: RecipeUpdate): Promise<Recipe> {
  return (
    await apiFetch(`/menu-items/${menuItemId}/recipe`, {
      method: "PUT",
      body: JSON.stringify(data),
    })
  ).json();
}
