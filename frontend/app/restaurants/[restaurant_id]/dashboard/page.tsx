import { getRestaurantDashboardAnalytics } from "@/lib/api/analytics";
import PageHeader from "@/components/ui/PageHeader";
import StatCard from "@/components/ui/StatCard";
import StatusBadge from "@/components/ui/StatusBadge";
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

function MetricTile({
    label,
    metric,
    formatter,
    tone,
}: {
    label: string;
    metric: DashboardMetric;
    formatter: (value: Money | number) => string;
    tone: "green" | "blue" | "amber";
}) {
    return (
        <StatCard
            label={label}
            value={formatter(metric.value)}
            tone={tone}
            detail={(
                <span className={getChangeClass(metric.change_percent)}>
                    {formatPercent(metric.change_percent)} vs yesterday
                </span>
            )}
        />
    );
}

function ChangeLine({
    metric,
}: {
    metric: DashboardMetric;
}) {
    return (
        <span className={getChangeClass(metric.change_percent)}>
                {formatPercent(metric.change_percent)} vs yesterday
        </span>
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
        <div className="h-72 rounded-lg border border-slate-200 bg-stone-50 px-4 py-5">
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
                                    className="w-full rounded-t-md bg-slate-900 transition"
                                    style={{
                                        height: `${height}%`,
                                    }}
                                    title={`${formatCurrency(point.sales)} from ${point.orders} orders`}
                                />
                            </div>

                            <div className="text-center">
                                <div className="text-xs font-medium text-slate-700">
                                    {formatDay(point.date)}
                                </div>

                                <div className="text-xs text-slate-500">
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
            <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center">
                <h2 className="text-lg font-semibold text-slate-950">
                    No completed item sales yet
                </h2>

                <p className="mx-auto mt-2 max-w-sm text-sm text-slate-600">
                    Top sellers will appear after customer orders are completed.
                </p>
            </div>
        );
    }

    return (
        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-6">
                <h2 className="text-lg font-semibold text-slate-950">
                    Top Selling Items
                </h2>

                <p className="text-sm text-slate-600">
                    Best-selling menu items from the last 7 days
                </p>
            </div>

            <div className="divide-y divide-slate-100">
                {analytics.top_selling_items.map((item, index) => (
                    <div
                        key={item.menu_item_id}
                        className="flex items-center justify-between gap-4 py-4"
                    >
                        <div className="flex min-w-0 items-center gap-4">
                            <span className="w-6 text-sm font-medium text-slate-400">
                                {index + 1}
                            </span>

                            <span className="truncate font-medium text-slate-950">
                                {item.name}
                            </span>
                        </div>

                        <div className="shrink-0 text-right text-sm text-slate-600">
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
            <PageHeader
                eyebrow="Command center"
                title="Restaurant Overview"
                description="Today&apos;s completed sales, order flow, and item movement across the restaurant."
                actions={<StatusBadge tone="green">Live operations</StatusBadge>}
            />

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <MetricTile
                    label="Sales"
                    metric={analytics.sales}
                    formatter={formatCurrency}
                    tone="green"
                />

                <MetricTile
                    label="Orders"
                    metric={analytics.orders}
                    formatter={formatNumber}
                    tone="blue"
                />

                <MetricTile
                    label="Average Order"
                    metric={analytics.average_order}
                    formatter={formatCurrency}
                    tone="amber"
                />
            </div>

            <div className="grid gap-6 xl:grid-cols-[1fr_22rem]">
                <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
                    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                            <h2 className="text-lg font-semibold text-slate-950">
                                Sales Rhythm
                            </h2>

                            <p className="text-sm text-slate-600">
                                Completed sales over the last 7 days
                            </p>
                        </div>

                        <ChangeLine metric={analytics.sales} />
                    </div>

                    <SalesChart points={analytics.sales_graph} />
                </div>

                <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
                    <h1>This is not implemented yet</h1>
                </div>
            </div>

            <TopSellingItems analytics={analytics} />
        </div>
    );
}
