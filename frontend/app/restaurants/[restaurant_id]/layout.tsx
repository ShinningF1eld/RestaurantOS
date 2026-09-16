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

    const restaurant = await getRestaurant(restaurantId).catch(() => ({
        id: restaurantId,
        name: `Restaurant #${restaurantId}`,
        address: "Mock location while the API is offline",
        phone: "Pending API",
    }));

    const navigation = [
        {
            name: "Dashboard",
            shortName: "Dash",
            href: `/restaurants/${restaurant_id}/dashboard`,
        },
        {
            name: "Orders",
            shortName: "Orders",
            href: `/restaurants/${restaurant_id}/orders`,
        },
        {
            name: "Menu",
            shortName: "Menu",
            href: `/restaurants/${restaurant_id}/menu`,
        },
        {
            name: "Tables",
            shortName: "Tables",
            href: `/restaurants/${restaurant_id}/tables`,
        },
        {
            name: "Inventory",
            shortName: "Stock",
            href: `/restaurants/${restaurant_id}/inventory`,
        },
        {
            name: "Employees",
            shortName: "Team",
            href: `/restaurants/${restaurant_id}/employees`,
        },
        {
            name: "Settings",
            shortName: "Setup",
            href: `/restaurants/${restaurant_id}/settings`,
        },
    ];

    return (
        <div className="min-h-screen bg-stone-50 text-slate-950">
            <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
                <div className="flex h-16 items-center justify-between px-4 sm:px-6 lg:px-8">
                    <Link
                        href="/dashboard/restaurants"
                        className="flex items-center gap-3"
                    >
                        <span className="flex h-9 w-9 items-center justify-center rounded-md bg-slate-950 text-sm font-semibold text-white">
                            OS
                        </span>
                        <span>
                            <span className="block text-sm font-semibold leading-5">
                                RestaurantOS
                            </span>
                            <span className="block text-xs text-slate-500">
                                Operations console
                            </span>
                        </span>
                    </Link>

                    <div className="flex items-center gap-4">
                        <div className="hidden text-right sm:block">
                            <p className="text-sm font-semibold">
                                {restaurant.name}
                            </p>
                            <p className="text-xs text-slate-500">
                                Live floor management
                            </p>
                        </div>

                        <div className="h-9 w-9 rounded-full border border-slate-200 bg-amber-100" />
                    </div>
                </div>
            </header>

            <div className="grid lg:grid-cols-[16rem_1fr]">
                <aside className="border-b border-slate-200 bg-white lg:min-h-[calc(100vh-4rem)] lg:border-b-0 lg:border-r">
                    <div className="hidden border-b border-slate-200 p-5 lg:block">
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                            Current restaurant
                        </p>
                        <p className="mt-2 text-sm font-semibold text-slate-950">
                            {restaurant.name}
                        </p>
                        <p className="mt-1 text-xs leading-5 text-slate-500">
                            {restaurant.address}
                        </p>
                    </div>

                    <nav className="flex gap-2 overflow-x-auto p-3 lg:flex-col lg:p-4">
                        {navigation.map((item) => (
                            <Link
                                key={item.name}
                                href={item.href}
                                className="flex shrink-0 items-center justify-between rounded-md px-3 py-2.5 text-sm font-semibold text-slate-600 transition hover:bg-stone-100 hover:text-slate-950 lg:w-full"
                            >
                                <span className="lg:hidden">{item.shortName}</span>
                                <span className="hidden lg:block">{item.name}</span>
                            </Link>
                        ))}
                    </nav>
                </aside>

                <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
                    <div className="mx-auto max-w-7xl">
                        {children}
                    </div>
                </main>
            </div>
        </div>
    );
}
