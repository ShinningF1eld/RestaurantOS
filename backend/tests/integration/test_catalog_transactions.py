from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import NotFoundError, ValidationError
from app.db.database import AsyncSessionLocal
from app.db.models.menu import Menu
from app.db.models.menu_items import MenuItem
from app.modules.catalog.service import (
    CatalogService, CreateMenu, CreateMenuItem, UpdateMenuItem,
)
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


@pytest.mark.asyncio
async def test_direct_service_rejects_prices_and_rolls_back_other_changes(owner_principal):
    async with AsyncSessionLocal() as session:
        restaurant = await RestaurantService(session, owner_principal).create(
            CreateRestaurant(name="Price test", address=None, phone=None)
        )
        catalog = CatalogService(session, owner_principal)
        menu = await catalog.create_menu(restaurant.id, CreateMenu("Main", None))
        menu_id = menu.menu_id
        item = await catalog.create_menu_item(
            menu_id, CreateMenuItem("Dish", None, Decimal("12.50"), True)
        )
        item_id = item.menu_item_id
        for price in (Decimal("-1"), Decimal("0.001"), Decimal("100000000")):
            with pytest.raises(ValidationError):
                await catalog.create_menu_item(
                    menu_id, CreateMenuItem("Invalid", None, price, True)
                )
            with pytest.raises(ValidationError):
                await catalog.update_menu_item(
                    item_id, UpdateMenuItem("Changed", None, price, None)
                )
        persisted = await session.get(MenuItem, item_id)
        assert persisted.name == "Dish"
        assert persisted.price == Decimal("12.50")
        assert len((await session.scalars(select(MenuItem))).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("price", ["-0.01", "NaN"])
async def test_database_rejects_invalid_stored_prices(owner_principal, price):
    async with AsyncSessionLocal() as session:
        restaurant = await RestaurantService(session, owner_principal).create(
            CreateRestaurant(name="Constraint test", address=None, phone=None)
        )
        catalog = CatalogService(session, owner_principal)
        menu = await catalog.create_menu(restaurant.id, CreateMenu("Main", None))
        with pytest.raises(IntegrityError, match="ck_menu_items_price_range"):
            async with session.begin():
                await session.execute(
                    text("INSERT INTO menu_items (menu_id, name, price, is_available) "
                         "VALUES (:menu, 'Invalid', CAST(:price AS numeric), true)"),
                    {"menu": menu.menu_id, "price": price},
                )
