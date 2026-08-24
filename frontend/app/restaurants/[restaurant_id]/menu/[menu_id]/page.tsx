import Link from "next/link";

import { getMenuItems } from "@/lib/api/menu_item";
import { getMenu} from "@/lib/api/menu";

import MenuItemList from "@/components/menu/MenuItemList";

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
                    {/* Back to menus */}
                    <Link
                        href={`/restaurants/${restaurantId}/menu`}
                        className="text-sm text-gray-500 transition hover:text-gray-900"
                    >
                        ← Back to Menus
                    </Link>

                    <h1 className="mt-3 text-2xl font-bold tracking-tight text-gray-900">
                        {menu.name}
                    </h1>

                    <p className="mt-1 text-sm text-gray-500">
                        {menu.description ||
                            "Manage the items in this menu."}
                    </p>
                </div>
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

            {/* Menu items */}
            <MenuItemList
                menuId={menuId}
                menuItems={menuItems}
            />
        </div>
    );
}