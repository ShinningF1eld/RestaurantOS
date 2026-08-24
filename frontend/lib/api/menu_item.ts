import type {
    MenuItem,
    MenuItemCreate,
    MenuItemUpdate,
} from "@/types/menu_item";

const API_URL = process.env.NEXT_PUBLIC_API_URL;


export async function getMenuItems(
    menuId: number
): Promise<MenuItem[]> {
    const response = await fetch(
        `${API_URL}/menus/${menuId}/items`
    );

    if (!response.ok) {
        throw new Error("Failed to fetch menu items");
    }

    return response.json();
}


export async function getMenuItem(
    menuItemId: number
): Promise<MenuItem> {
    const response = await fetch(
        `${API_URL}/menu-items/${menuItemId}`
    );

    if (!response.ok) {
        throw new Error("Failed to fetch menu item");
    }

    return response.json();
}


export async function createMenuItem(
    menuId: number,
    data: MenuItemCreate
): Promise<MenuItem> {
    const response = await fetch(
        `${API_URL}/menus/${menuId}/items`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(data),
        }
    );

    if (!response.ok) {
        throw new Error("Failed to create menu item");
    }

    return response.json();
}


export async function updateMenuItem(
    menuItemId: number,
    data: MenuItemUpdate
): Promise<MenuItem> {
    const response = await fetch(
        `${API_URL}/menu-items/${menuItemId}`,
        {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(data),
        }
    );

    if (!response.ok) {
        throw new Error("Failed to update menu item");
    }

    return response.json();
}


export async function deleteMenuItem(
    menuItemId: number
): Promise<void> {
    const response = await fetch(
        `${API_URL}/menu-items/${menuItemId}`,
        {
            method: "DELETE",
        }
    );

    if (!response.ok) {
        throw new Error("Failed to delete menu item");
    }
}