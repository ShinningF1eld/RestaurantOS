from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.db.database import AsyncSessionLocal
from app.db.models.menu import Menu
from app.db.models.menu_items import MenuItem
from app.modules.catalog.service import CatalogService, CreateMenu, CreateMenuItem
from app.modules.restaurants.service import (
    CreateRestaurant,
    RestaurantService,
    UpdateRestaurant,
)


@pytest.mark.asyncio
async def test_catalog_commands_commit_atomically_and_rollback_missing_parent(
    owner_principal,
) -> None:
    """Service commands commit complete writes and leave failed writes absent."""
    async with AsyncSessionLocal() as session:
        catalog_service = CatalogService(session, owner_principal)

        with pytest.raises(NotFoundError, match="Restaurant not found"):
            await catalog_service.create_menu(
                999_999,
                CreateMenu(name="Should not persist", description=None),
            )

        restaurant = await RestaurantService(session, owner_principal).create(
            CreateRestaurant(
                name="Transactional restaurant", address="Original address", phone=None
            )
        )
        restaurant = await RestaurantService(session, owner_principal).update(
            restaurant.id,
            UpdateRestaurant(
                name=None,
                address=None,
                phone=None,
                fields=frozenset({"address"}),
            ),
        )
        assert restaurant.address is None
        menu = await catalog_service.create_menu(
            restaurant.id,
            CreateMenu(name="Main", description="Lunch"),
        )
        item = await catalog_service.create_menu_item(
            menu.menu_id,
            CreateMenuItem(
                name="Dish",
                description=None,
                price=Decimal("12.50"),
                is_available=True,
            ),
        )
        outcome = await catalog_service.delete_menu_item(item.menu_item_id)

        assert outcome == "deleted"
        persisted_menus = (await session.execute(select(Menu))).scalars().all()
        persisted_items = (await session.execute(select(MenuItem))).scalars().all()
        assert [persisted_menu.menu_id for persisted_menu in persisted_menus] == [
            menu.menu_id
        ]
        assert persisted_items == []
