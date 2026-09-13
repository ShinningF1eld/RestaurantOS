import OrderActions from "./OrderActions";

import { getRestaurantOrders } from "@/lib/api/order";
import type { Money, Order } from "@/types/order";

interface OrdersPageProps {
    params: Promise<{
        restaurant_id: string;
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
    if (status === "complete") {
        return "bg-emerald-50 text-emerald-700 ring-emerald-200";
    }

    if (status === "cancelled") {
        return "bg-red-50 text-red-700 ring-red-200";
    }

    return "bg-amber-50 text-amber-700 ring-amber-200";
}

function OrderCard({
    order,
}: {
    order: Order;
}) {
    return (
        <article className="rounded-lg border bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                    <div className="flex flex-wrap items-center gap-3">
                        <h2 className="text-lg font-semibold text-gray-900">
                            Order #{order.order_id}
                        </h2>

                        <span
                            className={`rounded-full px-2.5 py-1 text-xs font-medium capitalize ring-1 ${getStatusClass(order.status)}`}
                        >
                            {order.status}
                        </span>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-gray-500">
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
                    <div className="text-2xl font-bold text-gray-900">
                        {formatCurrency(order.total)}
                    </div>

                    <p className="mt-1 text-sm text-gray-500">
                        {order.items.length}{" "}
                        {order.items.length === 1 ? "item" : "items"}
                    </p>
                </div>
            </div>

            <div className="mt-5 overflow-hidden rounded-lg border">
                <table className="w-full table-fixed divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
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

                    <tbody className="divide-y divide-gray-100 bg-white">
                        {order.items.map((item) => (
                            <tr key={item.order_item_id}>
                                <td className="px-4 py-3">
                                    <div className="font-medium text-gray-900">
                                        {item.menu_item_name}
                                    </div>

                                    {item.notes ? (
                                        <div className="mt-1 text-xs text-gray-500">
                                            {item.notes}
                                        </div>
                                    ) : null}
                                </td>

                                <td className="px-4 py-3 text-gray-700">
                                    {item.quantity}
                                </td>

                                <td className="px-4 py-3 text-gray-700">
                                    {formatCurrency(item.unit_price)}
                                </td>

                                <td className="px-4 py-3 text-right font-medium text-gray-900">
                                    {formatCurrency(item.line_total)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {order.notes ? (
                <p className="mt-4 rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-600">
                    {order.notes}
                </p>
            ) : null}

            <div className="mt-5 flex items-center justify-between border-t pt-4">
                <p className="text-sm text-gray-500">
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
}: OrdersPageProps) {
    const { restaurant_id } = await params;
    const restaurantId = Number(restaurant_id);
    const orders = await getRestaurantOrders(restaurantId);
    const openOrders = orders.filter(
        (order) => order.status !== "complete" && order.status !== "cancelled"
    );

    return (
        <div className="space-y-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">
                        Orders
                    </h1>

                    <p className="mt-1 text-sm text-gray-500">
                        Review customer orders and keep the kitchen flow current.
                    </p>
                </div>

                <div className="grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-lg border bg-white px-4 py-3">
                        <div className="font-semibold text-gray-900">
                            {openOrders.length}
                        </div>
                        <div className="text-gray-500">
                            Open
                        </div>
                    </div>

                    <div className="rounded-lg border bg-white px-4 py-3">
                        <div className="font-semibold text-gray-900">
                            {orders.length}
                        </div>
                        <div className="text-gray-500">
                            Total
                        </div>
                    </div>
                </div>
            </div>

            {orders.length === 0 ? (
                <div className="rounded-lg border border-dashed bg-white p-12 text-center">
                    <h2 className="text-lg font-semibold text-gray-900">
                        No customer orders yet
                    </h2>

                    <p className="mx-auto mt-2 max-w-sm text-sm text-gray-500">
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
        </div>
    );
}
