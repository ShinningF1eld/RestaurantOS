import OrderActions from "./OrderActions";
import Link from "next/link";

import { getRestaurantOrders } from "@/lib/api/order";
import PageHeader from "@/components/ui/PageHeader";
import StatCard from "@/components/ui/StatCard";
import StatusBadge from "@/components/ui/StatusBadge";
import type { Money, Order } from "@/types/order";
import OrderEntry from "./OrderEntry";
import { getRestaurantMenus } from "@/lib/api/menu";
import { getMenuItems } from "@/lib/api/menu_item";

interface OrdersPageProps {
    params: Promise<{
        restaurant_id: string;
    }>;
    searchParams: Promise<{
        offset?: string;
    }>;
}

function formatCurrency(value: Money) {
    return new Intl.NumberFormat("th-TH", {
        style: "currency",
        currency: "THB",
    }).format(Number(value));
}

function formatTime(value: string) {
    return new Intl.DateTimeFormat("en-US", {
        dateStyle: "medium",
        timeStyle: "short",
    }).format(new Date(value));
}

function getStatusClass(status: string) {
    if (status === "COMPLETED") {
        return "green";
    }

    if (status === "CANCELLED") {
        return "red";
    }

    return "amber";
}

function OrderCard({
    order,
}: {
    order: Order;
}) {
    return (
        <article className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                    <div className="flex flex-wrap items-center gap-3">
                        <h2 className="text-lg font-semibold text-slate-950">
                            Order #{order.order_id}
                        </h2>

                        <StatusBadge tone={getStatusClass(order.status) as "green" | "red" | "amber"}>
                            {order.status}
                        </StatusBadge>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-600">
                        <span>
                            {order.table_number
                                ? `Table ${order.table_number}`
                                : "No table"}
                        </span>

                        <span>
                            {order.customer_name || "Walk-in customer"}
                        </span>

                        <span>
                            {formatTime(order.created_at)}
                        </span>
                    </div>
                </div>

                <div className="text-left lg:text-right">
                    <div className="text-2xl font-semibold text-slate-950">
                        {formatCurrency(order.total)}
                    </div>

                    <p className="mt-1 text-sm text-slate-600">
                        {order.items.length}{" "}
                        {order.items.length === 1 ? "item" : "items"}
                    </p>
                </div>
            </div>

            <div className="mt-5 overflow-hidden rounded-lg border border-slate-200">
                <table className="w-full table-fixed divide-y divide-slate-200 text-sm">
                    <thead className="bg-stone-50 text-left text-xs font-semibold uppercase text-slate-500">
                        <tr>
                            <th className="w-24 px-4 py-3">
                                Item
                            </th>
                            <th className="w-20 px-4 py-3">
                                Qty
                            </th>
                            <th className="w-28 px-4 py-3">
                                Price
                            </th>
                            <th className="w-28 px-4 py-3 text-right">
                                Total
                            </th>
                        </tr>
                    </thead>

                    <tbody className="divide-y divide-slate-100 bg-white">
                        {order.items.map((item) => (
                            <tr key={item.order_item_id}>
                                <td className="px-4 py-3">
                                    <div className="font-medium text-slate-950">
                                        {item.menu_item_name}
                                    </div>

                                    {item.notes ? (
                                        <div className="mt-1 text-xs text-slate-500">
                                            {item.notes}
                                        </div>
                                    ) : null}
                                </td>

                                <td className="px-4 py-3 text-slate-700">
                                    {item.quantity}
                                </td>

                                <td className="px-4 py-3 text-slate-700">
                                    {formatCurrency(item.unit_price)}
                                </td>

                                <td className="px-4 py-3 text-right font-medium text-slate-950">
                                    {formatCurrency(item.line_total)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {order.notes ? (
                <p className="mt-4 rounded-md bg-stone-50 px-3 py-2 text-sm text-slate-600">
                    {order.notes}
                </p>
            ) : null}

            <div className="mt-5 flex flex-col gap-3 border-t border-slate-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-slate-500">
                    Last updated {formatTime(order.updated_at)}
                </p>

                <OrderActions
                    orderId={order.order_id}
                    status={order.status}
                />
            </div>
        </article>
    );
}

export default async function OrdersPage({
    params,
    searchParams,
}: OrdersPageProps) {
    const { restaurant_id } = await params;
    const { offset: requestedOffset } = await searchParams;
    const restaurantId = Number(restaurant_id);
    const limit = 25;
    const parsedOffset = Number(requestedOffset ?? 0);
    const offset = Number.isSafeInteger(parsedOffset) && parsedOffset >= 0
        ? parsedOffset
        : 0;
    const [orderPage, menus] = await Promise.all([
        getRestaurantOrders(restaurantId, limit, offset),
        getRestaurantMenus(restaurantId),
    ]);
    const menuItemLists = await Promise.all(menus.map((menu) => getMenuItems(menu.menu_id)));
    const orderableItems = menuItemLists.flat().filter((item) => item.is_available);
    const orders = orderPage.items;
    const openOrders = orders.filter(
        (order) => order.status !== "COMPLETED" && order.status !== "CANCELLED"
    );
    const completedOrders = orders.filter(
        (order) => order.status === "COMPLETED"
    );
    const cancelledOrders = orders.filter(
        (order) => order.status === "CANCELLED"
    );

    return (
        <div className="space-y-8">
            <PageHeader
                eyebrow="Service flow"
                title="Orders"
                description="Review customer orders, track ticket state, and keep the kitchen flow current."
            />

            <OrderEntry restaurantId={restaurantId} items={orderableItems} />

            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard
                    label="Open tickets"
                    value={openOrders.length}
                    detail="Need kitchen or floor action"
                    tone="amber"
                />
                <StatCard
                    label="Completed"
                    value={completedOrders.length}
                    detail="Closed during this view"
                    tone="green"
                />
                <StatCard
                    label="Cancelled"
                    value={cancelledOrders.length}
                    detail="Voids and stopped tickets"
                    tone="red"
                />
                <StatCard
                    label="Total tickets"
                    value={orderPage.total}
                    detail={`Showing ${orders.length} of all orders`}
                    tone="blue"
                />
            </div>

            {orders.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-300 bg-white p-12 text-center">
                    <h2 className="text-lg font-semibold text-slate-950">
                        No customer orders yet
                    </h2>

                    <p className="mx-auto mt-2 max-w-sm text-sm text-slate-600">
                        New orders will appear here as soon as customers place them.
                    </p>
                </div>
            ) : (
                <div className="space-y-4">
                    {orders.map((order) => (
                        <OrderCard
                            key={order.order_id}
                            order={order}
                        />
                    ))}
                </div>
            )}

            {orderPage.total > limit ? (
                <nav aria-label="Order pages" className="flex items-center justify-between border-t border-slate-200 pt-5">
                    <Link
                        aria-disabled={offset === 0}
                        href={offset === 0 ? "#" : `?offset=${Math.max(0, offset - limit)}`}
                        className={`rounded-md border px-4 py-2 text-sm font-semibold ${offset === 0 ? "pointer-events-none border-slate-100 text-slate-300" : "border-slate-200 bg-white text-slate-700 hover:bg-stone-50"}`}
                    >
                        Previous
                    </Link>
                    <span className="text-sm text-slate-600">
                        {offset + 1}–{Math.min(offset + orders.length, orderPage.total)} of {orderPage.total}
                    </span>
                    <Link
                        aria-disabled={offset + orders.length >= orderPage.total}
                        href={offset + orders.length >= orderPage.total ? "#" : `?offset=${offset + limit}`}
                        className={`rounded-md border px-4 py-2 text-sm font-semibold ${offset + orders.length >= orderPage.total ? "pointer-events-none border-slate-100 text-slate-300" : "border-slate-200 bg-white text-slate-700 hover:bg-stone-50"}`}
                    >
                        Next
                    </Link>
                </nav>
            ) : null}
        </div>
    );
}
