"""Queries used by alert consumers in the caller-owned transaction."""

from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.repo.models import (
    AlertEpisode,
    AlertIngredientState,
)
from app.modules.inventory.repo.models import (
    Ingredient,
    InventoryBalance,
    InventoryLowStockEpisode,
)


class AlertProjectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_page(
        self, organization_id: UUID, restaurant_id: int, limit: int, offset: int
    ) -> tuple[list[dict[str, object]], int]:
        # Live producer identity fences delayed resolution and superseded openings.
        statement = (
            select(
                AlertEpisode.episode_id,
                Ingredient.id.label("ingredient_id"),
                Ingredient.name.label("ingredient_name"),
                Ingredient.unit,
                InventoryBalance.quantity,
                Ingredient.reorder_threshold,
                AlertEpisode.opened_at,
                AlertEpisode.notification_suppressed,
            )
            .join(Ingredient, Ingredient.id == AlertEpisode.ingredient_id)
            .join(InventoryBalance, InventoryBalance.ingredient_id == Ingredient.id)
            .join(
                InventoryLowStockEpisode,
                InventoryLowStockEpisode.episode_id == AlertEpisode.episode_id,
            )
            .where(
                AlertEpisode.organization_id == organization_id,
                AlertEpisode.restaurant_id == restaurant_id,
                Ingredient.restaurant_id == restaurant_id,
                InventoryLowStockEpisode.organization_id == organization_id,
                InventoryLowStockEpisode.restaurant_id == restaurant_id,
                InventoryLowStockEpisode.ingredient_id == Ingredient.id,
                InventoryLowStockEpisode.resolved_at.is_(None),
                Ingredient.is_active.is_(True),
                InventoryBalance.quantity <= Ingredient.reorder_threshold,
            )
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        rows = await self.session.execute(
            statement.order_by(
                AlertEpisode.opened_at.desc(), AlertEpisode.episode_id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return [dict(row) for row in rows.mappings()], int(total or 0)

    async def history_page(
        self, organization_id: UUID, restaurant_id: int, limit: int, offset: int
    ) -> tuple[list[dict[str, object]], int]:
        statement = select(
            AlertEpisode.episode_id,
            AlertEpisode.ingredient_id,
            AlertEpisode.ingredient_name,
            AlertEpisode.unit,
            AlertEpisode.opening_quantity,
            AlertEpisode.opening_threshold,
            AlertEpisode.opened_at,
            AlertEpisode.opening_source,
            AlertEpisode.notification_suppressed,
            AlertEpisode.resolved_at,
            AlertEpisode.resolution_reason,
        ).where(
            AlertEpisode.organization_id == organization_id,
            AlertEpisode.restaurant_id == restaurant_id,
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        rows = await self.session.execute(
            statement.order_by(
                AlertEpisode.opened_at.desc(), AlertEpisode.episode_id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return [dict(row) for row in rows.mappings()], int(total or 0)

    async def episode(
        self, episode_id: UUID, *, lock: bool = False
    ) -> AlertEpisode | None:
        statement = select(AlertEpisode).where(AlertEpisode.episode_id == episode_id)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def state(
        self,
        organization_id: UUID,
        restaurant_id: int,
        ingredient_id: int,
        *,
        lock: bool = False,
    ) -> AlertIngredientState | None:
        statement = select(AlertIngredientState).where(
            AlertIngredientState.organization_id == organization_id,
            AlertIngredientState.restaurant_id == restaurant_id,
            AlertIngredientState.ingredient_id == ingredient_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def all_episodes(
        self, organization_id: UUID, restaurant_id: int
    ) -> list[AlertEpisode]:
        result = await self.session.scalars(
            select(AlertEpisode)
            .where(
                AlertEpisode.organization_id == organization_id,
                AlertEpisode.restaurant_id == restaurant_id,
            )
            .order_by(AlertEpisode.opened_at, AlertEpisode.episode_id)
        )
        return list(result)

    async def states(
        self, organization_id: UUID, restaurant_id: int
    ) -> list[AlertIngredientState]:
        return list(
            await self.session.scalars(
                select(AlertIngredientState)
                .where(
                    AlertIngredientState.organization_id == organization_id,
                    AlertIngredientState.restaurant_id == restaurant_id,
                )
                .order_by(AlertIngredientState.ingredient_id)
            )
        )
