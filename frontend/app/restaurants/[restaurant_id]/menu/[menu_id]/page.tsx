import Link from "next/link";

import { getMenu } from "@/lib/api/menu";
import { getMenuItems } from "@/lib/api/menu_item";

interface MenuItemsPageProps {
    params: Promise<{
        restaurant_id: string;
        menu_id: string;
    }>;
}

export default async function MenuItemsPage({
    params,
}: MenuItemsPageProps) {
    const { restaurant_id, menu_id } = await params;

    const restaurantId = Number(restaurant_id);
    const menuId = Number(menu_id);

    const [menu, menuItems] = await Promise.all([
        getMenu(menuId),
        getMenuItems(menuId),
    ]);

    return (
        <div className="space-y-8">
            {/* Header */}
            <div className="flex items-start justify-between">
                <div>
                    <Link
                        href={`/restaurants/${restaurantId}/menu`}
                        className="text-sm text-gray-500 hover:text-gray-900"
                    >
                        ← Back to Menus
                    </Link>

                    <h1 className="mt-3 text-2xl font-bold tracking-tight">
                        {menu.name}
                    </h1>

                    <p className="mt-1 text-sm text-gray-500">
                        {menu.description ||
                            "Manage the items in this menu."}
                    </p>
                </div>

                <button
                    type="button"
                    className="rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-gray-800"
                >
                    + Add Menu Item
                </button>
            </div>

            {/* Menu item count */}
            <div className="flex items-center gap-2 text-sm text-gray-500">
                <span className="font-medium text-gray-900">
                    {menuItems.length}
                </span>

                {menuItems.length === 1
                    ? "menu item"
                    : "menu items"}
            </div>

            {/* Menu Items */}
            {menuItems.length === 0 ? (
                <div className="rounded-xl border border-dashed bg-white p-12 text-center">
                    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-gray-100 text-xl">
                        🍽️
                    </div>

                    <h2 className="mt-4 text-lg font-semibold">
                        No menu items yet
                    </h2>

                    <p className="mx-auto mt-2 max-w-sm text-sm text-gray-500">
                        Add your first menu item to start building
                        this menu.
                    </p>

                    <button
                        type="button"
                        className="mt-6 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-gray-800"
                    >
                        Add your first item
                    </button>
                </div>
            ) : (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {menuItems.map((item) => (
                        <div
                            key={item.menu_item_id}
                            className="rounded-xl border bg-white p-5 shadow-sm transition hover:shadow-md"
                        >
                            <div className="flex items-start justify-between gap-4">
                                <div>
                                    <h2 className="font-semibold text-gray-900">
                                        {item.name}
                                    </h2>

                                    <p className="mt-1 text-sm text-gray-500">
                                        {item.description ||
                                            "No description provided."}
                                    </p>
                                </div>

                                <span
                                    className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
                                        item.is_available
                                            ? "bg-green-50 text-green-700"
                                            : "bg-gray-100 text-gray-500"
                                    }`}
                                >
                                    {item.is_available
                                        ? "Available"
                                        : "Unavailable"}
                                </span>
                            </div>

                            <div className="mt-5 flex items-center justify-between border-t pt-4">
                                <span className="text-lg font-bold text-gray-900">
                                    ฿{item.price.toLocaleString()}
                                </span>

                                <button
                                    type="button"
                                    className="text-sm font-medium text-gray-600 hover:text-gray-900"
                                >
                                    Edit
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}