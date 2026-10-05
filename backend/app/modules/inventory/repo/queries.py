from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import NotFoundError
from app.modules.inventory.repo.models import (
    Ingredient,
    InventoryBalance,
    InventoryMovement,
)
from app.modules.restaurants.repo.models import Restaurant
from app.modules.auth.repo.models import User
from app.modules.tenancy.access import restaurant_scope
from app.modules.tenancy.domain.policies import AccessContext


class InventoryRepository:
    def __init__(self, session: AsyncSession, context: AccessContext) -> None:
        self.session = session
        self.context = context

    async def lock_restaurant(self, restaurant_id: int) -> None:
        # Serializes ingredient names and opening-stock retries within this inventory.
        row = await self.session.scalar(
            select(Restaurant.id)
            .where(Restaurant.id == restaurant_id, restaurant_scope(self.context))
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("Restaurant not found")

    async def ingredients(
        self, restaurant_id: int, limit: int, offset: int
    ) -> list[tuple[Ingredient, InventoryBalance]]:
        rows = await self.session.execute(
            select(Ingredient, InventoryBalance)
            .join(InventoryBalance)
            .join(Restaurant)
            .where(
                Ingredient.restaurant_id == restaurant_id,
                restaurant_scope(self.context),
            )
            .order_by(Ingredient.name, Ingredient.id)
            .limit(limit)
            .offset(offset)
        )
        return [(item, balance) for item, balance in rows]

    async def ingredient(
        self, restaurant_id: int, ingredient_id: int, *, lock: bool = False
    ) -> tuple[Ingredient, InventoryBalance]:
        statement = (
            select(Ingredient, InventoryBalance)
            .join(InventoryBalance)
            .join(Restaurant)
            .where(
                Ingredient.id == ingredient_id,
                Ingredient.restaurant_id == restaurant_id,
                restaurant_scope(self.context),
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update(of=(Ingredient, InventoryBalance))
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            raise NotFoundError("Ingredient not found")
        return row[0], row[1]

    async def duplicate(
        self, restaurant_id: int, normalized_name: str, exclude: int = 0
    ) -> bool:
        return (
            await self.session.scalar(
                select(Ingredient.id)
                .join(Restaurant)
                .where(
                    Ingredient.restaurant_id == restaurant_id,
                    Ingredient.normalized_name == normalized_name,
                    Ingredient.id != exclude,
                    restaurant_scope(self.context),
                )
            )
            is not None
        )

    async def replay(
        self, restaurant_id: int, key: str, ingredient_id: int | None = None
    ) -> InventoryMovement | None:
        statement = (
            select(InventoryMovement)
            .join(Ingredient)
            .join(Restaurant)
            .where(
                Ingredient.restaurant_id == restaurant_id,
                InventoryMovement.idempotency_key == key,
                restaurant_scope(self.context),
            )
        )
        if ingredient_id is not None:
            statement = statement.where(Ingredient.id == ingredient_id)
        else:
            statement = statement.where(InventoryMovement.kind == "opening")
        return await self.session.scalar(statement)

    async def has_history(self, ingredient_id: int) -> bool:
        return (
            await self.session.scalar(
                select(InventoryMovement.id)
                .where(InventoryMovement.ingredient_id == ingredient_id)
                .limit(1)
            )
            is not None
        )

    async def movements(
        self, ingredient_id: int, limit: int, offset: int
    ) -> list[InventoryMovement]:
        rows = await self.session.execute(
            select(InventoryMovement, User.email)
            .join(Ingredient)
            .join(Restaurant)
            .outerjoin(User, InventoryMovement.actor_user_id == User.id)
            .where(
                InventoryMovement.ingredient_id == ingredient_id,
                restaurant_scope(self.context),
            )
            .order_by(InventoryMovement.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = []
        for movement, email in rows:
            movement.actor_name = email
            result.append(movement)
        return result
