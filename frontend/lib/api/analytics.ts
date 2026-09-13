import type { RestaurantDashboardAnalytics } from "@/types/analytics";

const API_URL = process.env.NEXT_PUBLIC_API_URL;


export async function getRestaurantDashboardAnalytics(
    restaurantId: number
): Promise<RestaurantDashboardAnalytics> {
    const response = await fetch(
        `${API_URL}/api/restaurants/${restaurantId}/analytics/dashboard`,
        {
            cache: "no-store",
        }
    );

    if (!response.ok) {
        throw new Error("Failed to fetch restaurant dashboard analytics");
    }

    return response.json();
}
