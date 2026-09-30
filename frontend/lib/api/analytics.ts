import { apiFetch } from "./client";
import type { RestaurantDashboardAnalytics } from "@/types/analytics";




export async function getRestaurantDashboardAnalytics(
    restaurantId: number
): Promise<RestaurantDashboardAnalytics> {
    const response = await apiFetch(
        `/api/restaurants/${restaurantId}/analytics/dashboard`,
        {
            cache: "no-store",
        }
    );

    if (!response.ok) {
        throw new Error("Failed to fetch restaurant dashboard analytics");
    }

    return response.json();
}
