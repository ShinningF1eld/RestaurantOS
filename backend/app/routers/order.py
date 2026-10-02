"""Compatibility imports; implementation belongs to the feature module."""

from app.modules.orders.router import (
    create_order as create_order,
    get_restaurant_orders as get_restaurant_orders,
    get_order as get_order,
    update_order as update_order,
    delete_order as delete_order,
    router as router,
)
