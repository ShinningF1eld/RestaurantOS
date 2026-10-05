"""Stable JSON snapshots of order creation results for idempotent replay."""

from app.modules.orders.repo.models import Order


def creation_response_snapshot(order: Order) -> dict[str, object]:
    """Return the public order response as JSON primitives at creation time."""
    return {
        "order_id": order.order_id,
        "restaurant_id": order.restaurant_id,
        "table_number": order.table_number,
        "customer_name": order.customer_name,
        "status": order.status,
        "payment_status": order.payment_status,
        "notes": order.notes,
        "subtotal": str(order.subtotal),
        "total": str(order.total),
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "items": [
            {
                "order_item_id": item.order_item_id,
                "order_id": item.order_id,
                "menu_item_id": item.menu_item_id,
                "menu_item_name": item.menu_item_name,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "line_total": str(item.line_total),
                "notes": item.notes,
            }
            for item in order.items
        ],
    }
