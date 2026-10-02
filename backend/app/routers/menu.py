"""Compatibility imports; implementation belongs to the feature module."""

from app.modules.catalog.menu_router import (
    create_menu as create_menu,
    get_restaurant_menus as get_restaurant_menus,
    get_menu as get_menu,
    update_menu as update_menu,
    delete_menu as delete_menu,
    router as router,
)
