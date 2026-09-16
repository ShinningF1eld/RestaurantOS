export type OrderStatus = "DRAFT" | "SUBMITTED" | "ACCEPTED" | "PREPARING" | "READY" | "COMPLETED" | "CANCELLED";
export type Money = number | string;

export interface OrderItem {
    order_item_id: number;
    order_id: number;
    menu_item_id: number | null;
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
    payment_status: "UNPAID" | "PAID" | "VOID";
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
    payment_status?: "UNPAID" | "PAID" | "VOID";
}

export interface OrderCreateItem {
    menu_item_id: number;
    quantity: number;
    notes?: string;
}

export interface OrderCreate {
    table_number?: string;
    customer_name?: string;
    notes?: string;
    items: OrderCreateItem[];
}

export interface PaginatedOrders {
    items: Order[];
    total: number;
    limit: number;
    offset: number;
}
