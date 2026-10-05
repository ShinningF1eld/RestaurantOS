"""Tenant-scoped recipe persistence operations."""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.repo.models import Menu, MenuItem
from app.modules.inventory.repo.models import Ingredient
from app.modules.recipes.repo.models import RecipeComponent
from app.modules.restaurants.repo.models import Restaurant
from app.modules.tenancy.access import restaurant_scope
from app.modules.tenancy.domain.policies import AccessContext


class RecipeRepository:
    def __init__(self, session: AsyncSession, context: AccessContext) -> None:
        self.session = session
        self.context = context

    async def menu_item(
        self, menu_item_id: int, *, lock: bool = False
    ) -> tuple[MenuItem, int] | None:
        statement = (
            select(MenuItem, Menu.restaurant_id)
            .join(Menu, Menu.menu_id == MenuItem.menu_id)
            .join(Restaurant, Restaurant.id == Menu.restaurant_id)
            .where(
                MenuItem.menu_item_id == menu_item_id,
                restaurant_scope(self.context),
            )
        )
        if lock:
            statement = statement.execution_options(populate_existing=True).with_for_update(
                of=MenuItem
            )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        return row[0], row[1]

    async def ingredients_for_restaurant(
        self, restaurant_id: int, ingredient_ids: Sequence[int]
    ) -> list[Ingredient]:
        if not ingredient_ids:
            return []
        result = await self.session.scalars(
            select(Ingredient)
            .where(
                Ingredient.restaurant_id == restaurant_id,
                Ingredient.id.in_(ingredient_ids),
            )
            .order_by(Ingredient.id)
        )
        return list(result.all())

    async def components_for_item(
        self, menu_item_id: int
    ) -> list[tuple[RecipeComponent, Ingredient]]:
        result = await self.session.execute(
            select(RecipeComponent, Ingredient)
            .join(Ingredient, Ingredient.id == RecipeComponent.ingredient_id)
            .join(MenuItem, MenuItem.menu_item_id == RecipeComponent.menu_item_id)
            .join(Menu, Menu.menu_id == MenuItem.menu_id)
            .join(Restaurant, Restaurant.id == Menu.restaurant_id)
            .where(
                RecipeComponent.menu_item_id == menu_item_id,
                restaurant_scope(self.context),
                Ingredient.restaurant_id == Menu.restaurant_id,
            )
            .order_by(RecipeComponent.id)
        )
        return [(component, ingredient) for component, ingredient in result.all()]

    async def replace_components(
        self, menu_item_id: int, components: Sequence[RecipeComponent]
    ) -> None:
        await self.session.execute(
            delete(RecipeComponent).where(RecipeComponent.menu_item_id == menu_item_id)
        )
        self.session.add_all(components)

    async def flush(self) -> None:
        await self.session.flush()


async def get_recipe_components(
    session: AsyncSession, menu_item_id: int
) -> list[tuple[RecipeComponent, Ingredient]]:
    """Return component rows with their fixed units for an internal caller.

    Callers that make business decisions should first tenant-scope the menu item
    and, for stock-sensitive work, hold that restaurant's inventory row lock.
    """
    result = await session.execute(
        select(RecipeComponent, Ingredient)
        .join(Ingredient, Ingredient.id == RecipeComponent.ingredient_id)
        .where(RecipeComponent.menu_item_id == menu_item_id)
        .order_by(RecipeComponent.id)
    )
    return [(component, ingredient) for component, ingredient in result.all()]
