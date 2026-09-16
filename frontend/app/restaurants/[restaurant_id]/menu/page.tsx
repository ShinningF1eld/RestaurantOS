import Link from "next/link";

import { getRestaurantMenus } from "@/lib/api/menu";

import CreateMenu from "@/components/menu/CreateMenu";
import EmptyState from "@/components/ui/EmptyState";
import PageHeader from "@/components/ui/PageHeader";
import StatCard from "@/components/ui/StatCard";
import StatusBadge from "@/components/ui/StatusBadge";

interface MenuPageProps {
    params: Promise<{
        restaurant_id: string;
    }>;
}

export default async function MenuPage({
    params,
}: MenuPageProps) {
    const { restaurant_id } = await params;

    const restaurantId = Number(restaurant_id);

    const menus = await getRestaurantMenus(restaurantId);

    return (
        <div className="space-y-8">
            <PageHeader
                eyebrow="Menu control"
                title="Menus"
                description="Organize menu sets for service periods, ordering channels, and seasonal offers."
                actions={<CreateMenu restaurantId={restaurantId} />}
            />

            <div className="grid gap-4 md:grid-cols-3">
                <StatCard
                    label="Menu sets"
                    value={menus.length}
                    detail={menus.length === 1 ? "Active menu" : "Active menus"}
                    tone="blue"
                />
            </div>

            {menus.length === 0 ? (
                <EmptyState
                    title="No menus yet"
                    description="Create your first menu to start adding dishes and managing the restaurant's offerings."
                    action={<CreateMenu restaurantId={restaurantId} />}
                />
            ) : (
                <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
                    {menus.map((menu) => (
                        <Link
                            key={menu.menu_id}
                            href={`/restaurants/${restaurantId}/menu/${menu.menu_id}`}
                            className="group"
                        >
                            <div className="h-full rounded-lg border border-slate-200 bg-white p-6 shadow-sm transition duration-200 hover:border-slate-300 hover:shadow-md">
                                <div className="flex items-start justify-between">
                                    <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-stone-100 text-sm font-semibold text-slate-700">
                                        MN
                                    </div>

                                    <StatusBadge tone="green">Active</StatusBadge>
                                </div>

                                <div className="mt-5">
                                    <h2 className="text-lg font-semibold text-slate-950 group-hover:text-slate-700">
                                        {menu.name}
                                    </h2>

                                    <p className="mt-2 min-h-10 text-sm leading-6 text-slate-600">
                                        {menu.description ||
                                            "No description provided."}
                                    </p>
                                </div>

                                <div className="mt-6 flex items-center justify-between border-t border-slate-200 pt-4">
                                    <span className="text-sm text-slate-500">
                                        Menu #{menu.menu_id}
                                    </span>

                                    <span className="text-sm font-semibold text-slate-950">
                                        View menu
                                    </span>
                                </div>
                            </div>
                        </Link>
                    ))}
                </div>
            )}
        </div>
    );
}
