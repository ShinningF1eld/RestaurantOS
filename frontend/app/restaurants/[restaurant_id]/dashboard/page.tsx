import { getRestaurantDashboardAnalytics } from "@/lib/api/analytics";
import type {
    DashboardMetric,
    RestaurantDashboardAnalytics,
    SalesPoint,
} from "@/types/analytics";
import type { Money } from "@/types/order";

interface DashboardPageProps {
    params: Promise<{
        restaurant_id: string;
    }>;
}

function formatCurrency(value: Money) {
    return new Intl.NumberFormat("th-TH", {
        style: "currency",
        currency: "THB",
        maximumFractionDigits: 0,
    }).format(Number(value));
}

function formatNumber(value: Money | number) {
    return new Intl.NumberFormat("en-US").format(Number(value));
}

function formatPercent(value: Money) {
    const numericValue = Number(value);
    const prefix = numericValue > 0 ? "+" : "";

    return `${prefix}${numericValue.toFixed(1)}%`;
}

function formatDay(value: string) {
    return new Intl.DateTimeFormat("en-US", {
        weekday: "short",
    }).format(new Date(`${value}T00:00:00`));
}

function getChangeClass(value: Money) {
    const numericValue = Number(value);

    if (numericValue > 0) {
        return "text-emerald-600";
    }

    if (numericValue < 0) {
        return "text-red-600";
    }

    return "text-gray-500";
}

function MetricCard({
    label,
    metric,
    formatter,
}: {
    label: string;
    metric: DashboardMetric;
    formatter: (value: Money | number) => string;
}) {
    return (
        <div className="rounded-lg border bg-white p-6 shadow-sm">
            <p className="text-sm text-gray-500">
                {label}
            </p>

            <p className="mt-2 text-3xl font-bold">
                {formatter(metric.value)}
            </p>

            <p className={`mt-2 text-sm ${getChangeClass(metric.change_percent)}`}>
                {formatPercent(metric.change_percent)} vs yesterday
            </p>
        </div>
    );
}

function SalesChart({
    points,
}: {
    points: SalesPoint[];
}) {
    const maxSales = Math.max(
        ...points.map((point) => Number(point.sales)),
        0
    );

    return (
        <div className="h-72 rounded-lg bg-gray-50 px-4 py-5">
            <div className="flex h-full items-end gap-3">
                {points.map((point) => {
                    const sales = Number(point.sales);
                    const height = maxSales > 0
                        ? Math.max((sales / maxSales) * 100, 4)
                        : 4;

                    return (
                        <div
                            key={point.date}
                            className="flex min-w-0 flex-1 flex-col items-center gap-2"
                        >
                            <div className="flex h-52 w-full items-end">
                                <div
                                    className="w-full rounded-t-md bg-gray-900 transition"
                                    style={{
                                        height: `${height}%`,
                                    }}
                                    title={`${formatCurrency(point.sales)} from ${point.orders} orders`}
                                />
                            </div>

                            <div className="text-center">
                                <div className="text-xs font-medium text-gray-700">
                                    {formatDay(point.date)}
                                </div>

                                <div className="text-xs text-gray-400">
                                    {formatCurrency(point.sales)}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function TopSellingItems({
    analytics,
}: {
    analytics: RestaurantDashboardAnalytics;
}) {
    if (analytics.top_selling_items.length === 0) {
        return (
            <div className="rounded-lg border border-dashed bg-white p-10 text-center">
                <h2 className="text-lg font-semibold">
                    No completed item sales yet
                </h2>

                <p className="mx-auto mt-2 max-w-sm text-sm text-gray-500">
                    Top sellers will appear after customer orders are completed.
                </p>
            </div>
        );
    }

    return (
        <div className="rounded-lg border bg-white p-6 shadow-sm">
            <div className="mb-6">
                <h2 className="text-lg font-semibold">
                    Top Selling Items
                </h2>

                <p className="text-sm text-gray-500">
                    Best-selling menu items from the last 7 days
                </p>
            </div>

            <div className="divide-y">
                {analytics.top_selling_items.map((item, index) => (
                    <div
                        key={item.menu_item_id}
                        className="flex items-center justify-between gap-4 py-4"
                    >
                        <div className="flex min-w-0 items-center gap-4">
                            <span className="w-6 text-sm font-medium text-gray-400">
                                {index + 1}
                            </span>

                            <span className="truncate font-medium">
                                {item.name}
                            </span>
                        </div>

                        <div className="shrink-0 text-right text-sm text-gray-500">
                            <div>
                                {formatNumber(item.quantity_sold)} sold
                            </div>

                            <div>
                                {formatCurrency(item.sales)}
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

export default async function DashboardPage({
    params,
}: DashboardPageProps) {
    const { restaurant_id } = await params;
    const restaurantId = Number(restaurant_id);
    const analytics = await getRestaurantDashboardAnalytics(restaurantId);

    return (
        <div className="space-y-8">
            <div>
                <h1 className="text-2xl font-bold">
                    Restaurant Overview
                </h1>

                <p className="mt-1 text-sm text-gray-500">
                    Today&apos;s completed sales and order activity.
                </p>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <MetricCard
                    label="Sales"
                    metric={analytics.sales}
                    formatter={formatCurrency}
                />

                <MetricCard
                    label="Orders"
                    metric={analytics.orders}
                    formatter={formatNumber}
                />

                <MetricCard
                    label="Average Order"
                    metric={analytics.average_order}
                    formatter={formatCurrency}
                />
            </div>

            <div className="rounded-lg border bg-white p-6 shadow-sm">
                <div className="mb-6">
                    <h2 className="text-lg font-semibold">
                        Sales
                    </h2>

                    <p className="text-sm text-gray-500">
                        Completed sales over the last 7 days
                    </p>
                </div>

                <SalesChart points={analytics.sales_graph} />
            </div>

            <TopSellingItems analytics={analytics} />
        </div>
    );
}
