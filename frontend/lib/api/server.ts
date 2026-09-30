import "server-only";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { checkResponse } from "./errors";
import { safeReturnPath } from "@/features/auth/paths";
import type { Restaurant } from "@/types/restaurant";
import type { Menu } from "@/types/menu";
import type { MenuItem } from "@/types/menu_item";
import type { PaginatedOrders } from "@/types/order";
import type { RestaurantDashboardAnalytics } from "@/types/analytics";

export { ApiError } from "./errors";

async function read<T>(path: string): Promise<T> {
  const origin = process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const access = (await cookies()).get("ros_access")?.value;
  const response = await fetch(`${origin.replace(/\/$/, "")}${path}`, {
    headers: access ? { Cookie: `ros_access=${encodeURIComponent(access)}` } : {},
    cache: "no-store",
    redirect: "error",
  });
  if (response.status === 401) {
    const next = safeReturnPath((await headers()).get("x-restaurantos-path"));
    redirect(`/session/renew?next=${encodeURIComponent(next)}`);
  }
  await checkResponse(response);
  return response.json() as Promise<T>;
}

export const getRestaurant = (id: number) => read<Restaurant>(`/api/restaurants/${id}`);
export const getRestaurantMenus = (id: number) => read<Menu[]>(`/restaurants/${id}/menus`);
export const getMenu = (id: number) => read<Menu>(`/menus/${id}`);
export const getMenuItems = (id: number) => read<MenuItem[]>(`/menus/${id}/items`);
export const getRestaurantOrders = (id: number, limit = 25, offset = 0) => read<PaginatedOrders>(`/api/restaurants/${id}/orders?limit=${limit}&offset=${offset}`);
export const getRestaurantDashboardAnalytics = (id: number) => read<RestaurantDashboardAnalytics>(`/api/restaurants/${id}/analytics/dashboard`);
