import type {
    Order,
    OrderUpdate,
} from "@/types/order";

const API_URL = process.env.NEXT_PUBLIC_API_URL;


export async function getRestaurantOrders(
    restaurantId: number
): Promise<Order[]> {
    const response = await fetch(
        `${API_URL}/api/restaurants/${restaurantId}/orders`,
        {
            cache: "no-store",
        }
    );

    if (!response.ok) {
        throw new Error("Failed to fetch orders");
    }

    return response.json();
}


export async function updateOrder(
    orderId: number,
    data: OrderUpdate
): Promise<Order> {
    const response = await fetch(
        `${API_URL}/api/orders/${orderId}`,
        {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(data),
        }
    );

    if (!response.ok) {
        throw new Error("Failed to update order");
    }

    return response.json();
}


export async function completeOrder(
    orderId: number
): Promise<Order> {
    return updateOrder(orderId, {
        status: "complete",
    });
}


export async function cancelOrder(
    orderId: number
): Promise<Order> {
    return updateOrder(orderId, {
        status: "cancelled",
    });
}
