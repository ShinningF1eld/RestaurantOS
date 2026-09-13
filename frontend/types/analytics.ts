import type { Money } from "@/types/order";

export interface DashboardMetric {
    value: Money | number;
    change_percent: Money;
}

export interface SalesPoint {
    date: string;
    sales: Money;
    orders: number;
}

export interface TopSellingItem {
    menu_item_id: number;
    name: string;
    quantity_sold: number;
    sales: Money;
}

export interface RestaurantDashboardAnalytics {
    sales: DashboardMetric;
    orders: DashboardMetric;
    average_order: DashboardMetric;
    sales_graph: SalesPoint[];
    top_selling_items: TopSellingItem[];
}
