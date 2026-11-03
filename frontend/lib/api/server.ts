import "server-only";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { checkResponse } from "./errors";
import { safeReturnPath } from "@/features/auth/paths";
import { trace, SpanKind, SpanStatusCode } from "@opentelemetry/api";
import { apiTraceHeaders } from "@/lib/telemetry/context";
import type { Restaurant } from "@/types/restaurant";
import type { Menu } from "@/types/menu";
import type { MenuItem } from "@/types/menu_item";
import type { PaginatedOrders } from "@/types/order";
import type { RestaurantDashboardAnalytics } from "@/types/analytics";
import type { AccessContext, Membership } from "@/types/access";

export { ApiError } from "./errors";

async function read<T>(path: string): Promise<T> {
  const origin = process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const access = (await cookies()).get("ros_access")?.value;
  const destination = new URL(`${origin.replace(/\/$/, "")}${path}`);
  const response = await trace
    .getTracer("restaurantos.frontend", "1")
    .startActiveSpan("API request", { kind: SpanKind.CLIENT }, async (span) => {
      try {
        return await fetch(destination.href, {
          headers: {
            ...apiTraceHeaders(destination, new URL(origin).origin),
            ...(access ? { Cookie: `ros_access=${encodeURIComponent(access)}` } : {}),
          },
          cache: "no-store",
          redirect: "error",
        });
      } catch (error) {
        span.setStatus({ code: SpanStatusCode.ERROR });
        throw error;
      } finally {
        span.end();
      }
    });
  if (response.status === 401) {
    const next = safeReturnPath((await headers()).get("x-restaurantos-path"));
    redirect(`/session/renew?next=${encodeURIComponent(next)}`);
  }
  await checkResponse(response);
  return response.json() as Promise<T>;
}

export const getRestaurant = (id: number) => read<Restaurant>(`/api/restaurants/${id}`);
export const getAccess = () => read<AccessContext>("/api/access");
export const getMemberships = () => read<Membership[]>("/api/memberships");
export const getRestaurantMenus = (id: number) => read<Menu[]>(`/restaurants/${id}/menus`);
export const getMenu = (id: number) => read<Menu>(`/menus/${id}`);
export const getMenuItems = (id: number) => read<MenuItem[]>(`/menus/${id}/items`);
export const getRestaurantOrders = (id: number, limit = 25, offset = 0) =>
  read<PaginatedOrders>(`/api/restaurants/${id}/orders?limit=${limit}&offset=${offset}`);
export const getRestaurantDashboardAnalytics = (id: number) =>
  read<RestaurantDashboardAnalytics>(`/api/restaurants/${id}/analytics/dashboard`);
