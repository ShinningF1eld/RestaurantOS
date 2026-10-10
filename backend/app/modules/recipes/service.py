"""Recipe writes and shared menu stock availability calculations."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.audit.service import record
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.catalog.repo.models import Menu, MenuItem
from app.modules.inventory.domain.policies import quantity as validate_quantity
from app.modules.inventory.repo.models import (
    Ingredient,
    InventoryBalance,
)
from app.modules.inventory.repo.queries import InventoryRepository
from app.modules.recipes.domain.commands import ReplaceRecipe
from app.modules.recipes.repo.models import RecipeComponent
from app.modules.recipes.repo.queries import RecipeRepository
from app.modules.tenancy.access import AccessService


@dataclass(frozen=True, slots=True)
class RecipeComponentView:
    ingredient_id: int
    ingredient_name: str
    unit: str
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class RecipeView:
    menu_item_id: int
    restaurant_id: int
    inventory_tracking: bool
    components: list[RecipeComponentView]


@dataclass(frozen=True, slots=True)
class MenuItemAvailability:
    restaurant_id: int
    inventory_tracking: bool
    out_of_stock: bool
    available_portions: int | None


class RecipeAvailabilityService:
    """Compute present stock coverage for already authorized menu items."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def for_menu_items(
        self,
        menu_items: Sequence[MenuItem],
        *,
        expected_menu_id: int | None = None,
    ) -> dict[int, MenuItemAvailability]:
        if not menu_items:
            return {}

        item_ids = [item.menu_item_id for item in menu_items]
        statement = (
            select(
                MenuItem.menu_item_id,
                MenuItem.menu_id,
                MenuItem.inventory_tracking,
                Menu.restaurant_id,
                RecipeComponent.id,
                RecipeComponent.quantity,
                Ingredient.id,
                Ingredient.restaurant_id,
                Ingredient.is_active,
                InventoryBalance.quantity,
            )
            .select_from(MenuItem)
            .join(Menu, Menu.menu_id == MenuItem.menu_id)
            .outerjoin(
                RecipeComponent,
                RecipeComponent.menu_item_id == MenuItem.menu_item_id,
            )
            .outerjoin(Ingredient, Ingredient.id == RecipeComponent.ingredient_id)
            .outerjoin(
                InventoryBalance,
                InventoryBalance.ingredient_id == RecipeComponent.ingredient_id,
            )
            .where(MenuItem.menu_item_id.in_(item_ids))
            .order_by(MenuItem.menu_item_id, RecipeComponent.id)
        )
        if expected_menu_id is not None:
            statement = statement.where(MenuItem.menu_id == expected_menu_id)
        rows = await self.session.execute(statement)

        restaurant_ids: dict[int, int] = {}
        menu_ids: dict[int, int] = {}
        tracking: dict[int, bool] = {}
        components: dict[
            int,
            list[tuple[Decimal, int | None, int | None, bool | None, Decimal | None]],
        ] = {item_id: [] for item_id in item_ids}
        for (
            item_id,
            menu_id,
            inventory_tracking,
            restaurant_id,
            component_id,
            required,
            ingredient_id,
            ingredient_restaurant_id,
            active,
            balance,
        ) in rows.all():
            restaurant_ids[item_id] = restaurant_id
            menu_ids[item_id] = menu_id
            tracking[item_id] = inventory_tracking
            if component_id is not None:
                components[item_id].append(
                    (
                        required,
                        ingredient_id,
                        ingredient_restaurant_id,
                        active,
                        balance,
                    )
                )

        availability: dict[int, MenuItemAvailability] = {}
        for item in menu_items:
            # A cached item can have been deleted or moved to another menu since
            # the cache fill. Omit it so the caller can treat that entry as a miss.
            if (
                item.menu_item_id not in tracking
                or menu_ids[item.menu_item_id] != item.menu_id
            ):
                continue
            tracked = bool(tracking[item.menu_item_id])
            if not tracked:
                availability[item.menu_item_id] = MenuItemAvailability(
                    restaurant_id=restaurant_ids[item.menu_item_id],
                    inventory_tracking=False,
                    out_of_stock=False,
                    available_portions=None,
                )
                continue

            recipe = components[item.menu_item_id]
            portions: list[int] = []
            has_unavailable_component = not recipe
            for (
                required,
                ingredient_id,
                ingredient_restaurant_id,
                active,
                balance,
            ) in recipe:
                if (
                    ingredient_id is None
                    or ingredient_restaurant_id != restaurant_ids[item.menu_item_id]
                    or not active
                    or balance is None
                    or required <= 0
                ):
                    has_unavailable_component = True
                    continue
                portions.append(int(balance // required))

            available_portions = min(portions) if portions else 0
            if has_unavailable_component:
                available_portions = 0
            availability[item.menu_item_id] = MenuItemAvailability(
                restaurant_id=restaurant_ids[item.menu_item_id],
                inventory_tracking=True,
                out_of_stock=has_unavailable_component or available_portions == 0,
                available_portions=available_portions,
            )
        return availability


class RecipesService:
    def __init__(
        self, session: AsyncSession, principal: AuthenticatedPrincipal
    ) -> None:
        self.session = session
        self.access = AccessService(session, principal)

    async def get(self, menu_item_id: int) -> RecipeView:
        context = await self.access.current()
        repository = RecipeRepository(self.session, context)
        # Keep tracking and component reads coherent while a recipe is replaced.
        # This read takes only the item lock, and performs no later lock acquisition.
        found = await repository.menu_item(menu_item_id, lock=True)
        if found is None:
            raise NotFoundError("Menu item not found")
        item, restaurant_id = found
        context.require("menu.read")
        components = await repository.components_for_item(menu_item_id)
        return RecipeView(
            menu_item_id=menu_item_id,
            restaurant_id=restaurant_id,
            inventory_tracking=item.inventory_tracking,
            components=[
                RecipeComponentView(
                    ingredient_id=component.ingredient_id,
                    ingredient_name=ingredient.name,
                    unit=ingredient.unit,
                    quantity=component.quantity,
                )
                for component, ingredient in components
            ],
        )

    async def replace(self, menu_item_id: int, command: ReplaceRecipe) -> RecipeView:
        async with self.session.begin():
            context = await self.access.current(lock=True)
            repository = RecipeRepository(self.session, context)
            found = await repository.menu_item(menu_item_id)
            if found is None:
                raise NotFoundError("Menu item not found")
            _, restaurant_id = found
            context.require("menu.manage")

            # Share the restaurant lock used by every inventory mutation and order
            # acceptance, then lock the menu item before validating/replacing it.
            await InventoryRepository(self.session, context).lock_restaurant(
                restaurant_id
            )
            found = await repository.menu_item(menu_item_id, lock=True)
            if found is None:
                raise NotFoundError("Menu item not found")
            item, restaurant_id = found

            component_inputs = command.components
            ingredient_ids = [component.ingredient_id for component in component_inputs]
            if len(set(ingredient_ids)) != len(ingredient_ids):
                raise ValidationError("A recipe cannot contain duplicate ingredients")
            if command.inventory_tracking and not component_inputs:
                raise ValidationError(
                    "Inventory tracking requires at least one recipe ingredient"
                )
            for component in component_inputs:
                validate_quantity(component.quantity, positive=True)

            ingredients = await repository.ingredients_for_restaurant(
                restaurant_id, ingredient_ids
            )
            ingredients_by_id = {
                ingredient.id: ingredient for ingredient in ingredients
            }
            if len(ingredients_by_id) != len(ingredient_ids):
                raise NotFoundError("Ingredient not found")
            if any(not ingredient.is_active for ingredient in ingredients):
                raise ConflictError(
                    "Restore inactive ingredients before using them in a recipe"
                )

            item.inventory_tracking = command.inventory_tracking
            components = [
                RecipeComponent(
                    menu_item_id=menu_item_id,
                    ingredient_id=component.ingredient_id,
                    quantity=component.quantity,
                )
                for component in component_inputs
            ]
            await repository.replace_components(menu_item_id, components)
            await repository.flush()
            record(
                self.session,
                context,
                "menu_item.recipe.updated",
                "menu_item",
                menu_item_id,
                restaurant_id=restaurant_id,
            )
            return RecipeView(
                menu_item_id=menu_item_id,
                restaurant_id=restaurant_id,
                inventory_tracking=item.inventory_tracking,
                components=[
                    RecipeComponentView(
                        ingredient_id=component.ingredient_id,
                        ingredient_name=ingredients_by_id[component.ingredient_id].name,
                        unit=ingredients_by_id[component.ingredient_id].unit,
                        quantity=component.quantity,
                    )
                    for component in component_inputs
                ],
            )
