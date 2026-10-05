import SessionMenu from "@/features/auth/SessionMenu";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ReactNode } from "react";

import { ApiError, getAccess, getRestaurant } from "@/lib/api/server";

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
    if (!Number.isSafeInteger(restaurantId) || restaurantId <= 0) {
        notFound();
    }

    let restaurant;
    try {
        restaurant = await getRestaurant(restaurantId);
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
            notFound();
        }
        throw error;
    }

    const access = await getAccess();
    const navigation = [
        {
            name: "Dashboard", capability: "analytics.read",
            shortName: "Dash",
            href: `/restaurants/${restaurant_id}/dashboard`,
        },
        {
            name: "Orders", capability: "order.read",
            shortName: "Orders",
            href: `/restaurants/${restaurant_id}/orders`,
        },
        {
            name: "Menu", capability: "menu.read",
            shortName: "Menu",
            href: `/restaurants/${restaurant_id}/menu`,
        },
        {
            name: "Tables", capability: "restaurant.update",
            shortName: "Tables",
            href: `/restaurants/${restaurant_id}/tables`,
        },
        {
            name: "Inventory", capability: "inventory.read",
            shortName: "Stock",
            href: `/restaurants/${restaurant_id}/inventory`,
        },
        {
            name: "Employees", capability: "staff.manage",
            shortName: "Team",
            href: `/restaurants/${restaurant_id}/employees`,
        },
        {
            name: "Settings", capability: "restaurant.update",
            shortName: "Setup",
            href: `/restaurants/${restaurant_id}/settings`,
        },
    ].filter(item => access.capabilities.includes(item.capability));

    return (
        <div className="min-h-screen bg-stone-50 text-slate-950">
            <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
                <div className="flex min-h-16 flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-2 sm:px-6 lg:px-8">
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

                    <div className="flex min-w-0 items-center gap-4">
                        <div className="hidden text-right sm:block">
                            <p className="text-sm font-semibold">
                                {restaurant.name}
                            </p>
                            <p className="text-xs text-slate-500">
                                Live floor management
                            </p>
                        </div>

                        <SessionMenu />
                    </div>
                </div>
            </header>

            <div className="grid min-w-0 lg:grid-cols-[16rem_minmax(0,1fr)]">
                <aside className="min-w-0 border-b border-slate-200 bg-white lg:min-h-[calc(100vh-4rem)] lg:border-b-0 lg:border-r">
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
