export type OrderStatus = "pending" | "complete" | "cancelled" | string;
export type Money = number | string;

export interface OrderItem {
    order_item_id: number;
    order_id: number;
    menu_item_id: number;
    menu_item_name: string;
    quantity: number;
    unit_price: Money;
    line_total: Money;
    notes: string | null;
}

export interface Order {
    order_id: number;
    restaurant_id: number;
    table_number: string | null;
    customer_name: string | null;
    status: OrderStatus;
    notes: string | null;
    subtotal: Money;
    total: Money;
    created_at: string;
    updated_at: string;
    items: OrderItem[];
}

export interface OrderUpdate {
    table_number?: string | null;
    customer_name?: string | null;
    status?: OrderStatus;
    notes?: string | null;
}
