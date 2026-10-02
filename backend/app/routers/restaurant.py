"""Compatibility imports; implementation belongs to the feature module."""

from app.modules.restaurants.router import (
    create_restaurant as create_restaurant,
    get_restaurants as get_restaurants,
    get_restaurant as get_restaurant,
    update_restaurant as update_restaurant,
    delete_restaurant as delete_restaurant,
    router as router,
)
