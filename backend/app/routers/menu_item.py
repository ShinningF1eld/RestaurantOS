"""Compatibility imports; implementation belongs to the feature module."""

from app.modules.catalog.item_router import (
    create_menu_item as create_menu_item,
    get_menu_items as get_menu_items,
    get_menu_item as get_menu_item,
    update_menu_item as update_menu_item,
    delete_menu_item as delete_menu_item,
    router as router,
)
