"""Queries used by alert consumers in the caller-owned transaction."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.repo.models import (
    AlertEpisode,
    AlertIngredientState,
)


class AlertProjectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
