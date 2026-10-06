"use client";
import { apiFetch } from "./client";
import type { Ingredient, Movement } from "@/types/inventory";
export function inventoryApi(restaurantId: number) {
  const base = `/api/restaurants/${restaurantId}/inventory/ingredients`;
  return {
    list: async (offset = 0): Promise<Ingredient[]> =>
      (await apiFetch(`${base}?limit=100&offset=${offset}`)).json(),
    create: async (data: object): Promise<Ingredient> =>
      (await apiFetch(base, { method: "POST", body: JSON.stringify(data) })).json(),
    update: async (id: number, data: object): Promise<Ingredient> =>
      (await apiFetch(`${base}/${id}`, { method: "PUT", body: JSON.stringify(data) })).json(),
    stock: async (id: number, data: object): Promise<Movement> =>
      (
        await apiFetch(`${base}/${id}/movements`, { method: "POST", body: JSON.stringify(data) })
      ).json(),
    history: async (id: number, offset = 0): Promise<Movement[]> =>
      (await apiFetch(`${base}/${id}/movements?limit=20&offset=${offset}`)).json(),
  };
}
