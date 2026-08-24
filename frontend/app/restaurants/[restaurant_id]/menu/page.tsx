import Link from "next/link";

import { getRestaurantMenus } from "@/lib/api/menu";

import CreateMenu from "@/components/menu/CreateMenu";

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
            {/* Page Header */}
            <div className="flex items-start justify-between">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">
                        Menus
                    </h1>

                    <p className="mt-1 text-sm text-gray-500">
                        Manage your restaurant menus and menu items.
                    </p>
                </div>

                <CreateMenu restaurantId={restaurantId} />
            </div>

            {/* Menu count */}
            <div className="flex items-center gap-2 text-sm text-gray-500">
                <span className="font-medium text-gray-900">
                    {menus.length}
                </span>
                {menus.length === 1 ? "menu" : "menus"}
            </div>

            {/* Menu List */}
            {menus.length === 0 ? (
                <div className="rounded-xl border border-dashed bg-white p-12 text-center">
                    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-gray-100 text-xl">
                        🍽️
                    </div>

                    <h2 className="mt-4 text-lg font-semibold">
                        No menus yet
                    </h2>

                    <p className="mx-auto mt-2 max-w-sm text-sm text-gray-500">
                        Create your first menu to start adding dishes and
                        managing your restaurant's offerings.
                    </p>

                    <button
                        type="button"
                        className="mt-6 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-gray-800"
                    >
                        Create your first menu
                    </button>
                </div>
            ) : (
                <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
                    {menus.map((menu) => (
                        <Link
                            key={menu.menu_id}
                            href={`/restaurants/${restaurantId}/menu/${menu.menu_id}`}
                            className="group"
                        >
                            <div className="h-full rounded-xl border bg-white p-6 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:border-gray-300 hover:shadow-md">
                                <div className="flex items-start justify-between">
                                    <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-gray-100 text-xl">
                                        🍴
                                    </div>

                                    <span className="rounded-full bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700">
                                        Active
                                    </span>
                                </div>

                                <div className="mt-5">
                                    <h2 className="text-lg font-semibold text-gray-900 group-hover:text-gray-700">
                                        {menu.name}
                                    </h2>

                                    <p className="mt-2 min-h-10 text-sm leading-5 text-gray-500">
                                        {menu.description ||
                                            "No description provided."}
                                    </p>
                                </div>

                                <div className="mt-6 flex items-center justify-between border-t pt-4">
                                    <span className="text-sm text-gray-500">
                                        Menu #{menu.menu_id}
                                    </span>

                                    <span className="text-sm font-medium text-gray-900">
                                        View menu →
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