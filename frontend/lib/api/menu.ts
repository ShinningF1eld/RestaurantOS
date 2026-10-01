import { apiFetch } from "./client";
import type {
    Menu,
    MenuCreate,
    MenuUpdate,
} from "@/types/menu";




export async function getRestaurantMenus(
    restaurantId: number
): Promise<Menu[]> {
    const response = await apiFetch(
        `/restaurants/${restaurantId}/menus`
    );

    if (!response.ok) {
        throw new Error("Failed to fetch menus");
    }

    return response.json();
}


export async function getMenu(
    menuId: number
): Promise<Menu> {
    const response = await apiFetch(
        `/menus/${menuId}`
    );

    if (!response.ok) {
        throw new Error("Failed to fetch menu");
    }

    return response.json();
}


export async function createMenu(
    restaurantId: number,
    data: MenuCreate
): Promise<Menu> {
    const response = await apiFetch(
        `/restaurants/${restaurantId}/menus`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(data),
        }
    );

    if (!response.ok) {
        throw new Error("Failed to create menu");
    }

    return response.json();
}


export async function updateMenu(
    menuId: number,
    data: MenuUpdate
): Promise<Menu> {
    const response = await apiFetch(
        `/menus/${menuId}`,
        {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(data),
        }
    );

    if (!response.ok) {
        throw new Error("Failed to update menu");
    }

    return response.json();
}


export async function deleteMenu(
    menuId: number
): Promise<void> {
    const response = await apiFetch(
        `/menus/${menuId}`,
        {
            method: "DELETE",
        }
    );

    if (!response.ok) {
        throw new Error("Failed to delete menu");
    }
}