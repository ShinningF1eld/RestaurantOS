import Link from "next/link";
import { ReactNode } from "react";

import { getRestaurant } from "@/lib/api/restaurant";

interface RestaurantLayoutProps {
    children: ReactNode;
    params: Promise<{
        restaurant_id: string;
    }>;
}

export default async function RestaurantLayout({
    children,
    params,
}: RestaurantLayoutProps) {
    const { restaurant_id } = await params;

    const restaurantId = Number(restaurant_id);

    const restaurant = await getRestaurant(restaurantId);

    const navigation = [
        {
            name: "Dashboard",
            href: `/restaurants/${restaurant_id}/dashboard`,
        },
        {
            name: "Orders",
            href: `/restaurants/${restaurant_id}/orders`,
        },
        {
            name: "Menu",
            href: `/restaurants/${restaurant_id}/menu`,
        },
        {
            name: "Tables",
            href: `/restaurants/${restaurant_id}/tables`,
        },
        {
            name: "Inventory",
            href: `/restaurants/${restaurant_id}/inventory`,
        },
        {
            name: "Employees",
            href: `/restaurants/${restaurant_id}/employees`,
        },
        {
            name: "Settings",
            href: `/restaurants/${restaurant_id}/settings`,
        },
    ];

    return (
        <div className="min-h-screen bg-gray-50 text-gray-900">
            {/* Top bar */}
            <header className="flex h-16 items-center justify-between border-b bg-white px-6">
                <div className="text-xl font-bold">
                    RestaurantOS
                </div>

                <div className="flex items-center gap-4">
                    <span className="text-sm font-medium">
                        {restaurant.name}
                    </span>

                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gray-200">
                        👤
                    </div>
                </div>
            </header>

            <div className="flex">
                {/* Sidebar */}
                <aside className="min-h-[calc(100vh-4rem)] w-60 border-r bg-white p-4">
                    <nav className="space-y-1">
                        {navigation.map((item) => (
                            <Link
                                key={item.name}
                                href={item.href}
                                className="block rounded-lg px-4 py-3 text-sm font-medium text-gray-700 transition hover:bg-gray-100 hover:text-gray-900"
                            >
                                {item.name}
                            </Link>
                        ))}
                    </nav>
                </aside>

                {/* Page content */}
                <main className="flex-1 p-8">
                    {children}
                </main>
            </div>
        </div>
    );
}