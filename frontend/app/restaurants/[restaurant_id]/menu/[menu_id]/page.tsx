import Link from "next/link";

import { getMenuItems } from "@/lib/api/menu_item";
import { getMenu} from "@/lib/api/menu";

import MenuItemList from "@/components/menu/MenuItemList";
import PageHeader from "@/components/ui/PageHeader";
import StatCard from "@/components/ui/StatCard";

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
    const availableItems = menuItems.filter((item) => item.is_available);

    return (
        <div className="space-y-8">
            <PageHeader
                eyebrow="Menu detail"
                title={menu.name}
                description={menu.description || "Manage item availability, pricing, and descriptions for this menu."}
                actions={(
                    <Link
                        href={`/restaurants/${restaurantId}/menu`}
                        className="rounded-md border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-stone-50"
                    >
                        Back to menus
                    </Link>
                )}
            />

            <div className="grid gap-4 md:grid-cols-3">
                <StatCard
                    label="Items"
                    value={menuItems.length}
                    detail={menuItems.length === 1 ? "Menu item" : "Menu items"}
                    tone="blue"
                />
                <StatCard
                    label="Available"
                    value={availableItems.length}
                    detail="Ready for ordering"
                    tone="green"
                />
            </div>

            <MenuItemList
                menuId={menuId}
                menuItems={menuItems}
            />
        </div>
    );
}
