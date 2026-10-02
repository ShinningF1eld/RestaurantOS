"""Organization and membership persistence without transaction ownership."""

from uuid import UUID
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.tenancy.repo.models import (
    Membership,
    Organization,
    RestaurantAssignment,
)
from app.modules.tenancy.domain.roles import MembershipRole
from app.modules.restaurants.repo.models import Restaurant
from app.modules.auth.repo.models import User


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_organization(self, organization_id: UUID) -> None:
        await self._session.execute(
            select(Organization.id)
            .where(Organization.id == organization_id)
            .with_for_update()
        )

    async def get(
        self, membership_id: UUID, organization_id: UUID
    ) -> Membership | None:
        return await self._session.scalar(
            select(Membership)
            .where(
                Membership.id == membership_id,
                Membership.organization_id == organization_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )

    async def organization(self, organization_id: UUID) -> Organization | None:
        return await self._session.scalar(
            select(Organization).where(Organization.id == organization_id)
        )

    async def for_user(self, user_id: UUID) -> Membership | None:
        return await self._session.scalar(
            select(Membership).where(Membership.user_id == user_id)
        )

    async def list_for_organization(self, organization_id: UUID) -> list[Membership]:
        return list(
            (
                await self._session.scalars(
                    select(Membership)
                    .where(Membership.organization_id == organization_id)
                    .order_by(Membership.created_at, Membership.id)
                )
            ).all()
        )

    async def owner_count(self, organization_id: UUID) -> int:
        return int(
            await self._session.scalar(
                select(func.count(Membership.id))
                .join(User)
                .where(
                    Membership.organization_id == organization_id,
                    Membership.status == "active",
                    Membership.role == MembershipRole.OWNER,
                    User.status == "active",
                )
            )
            or 0
        )

    async def assign(self, member: Membership, restaurant_ids: list[int]) -> bool:
        ids = set(restaurant_ids)
        allowed = set(
            (
                await self._session.scalars(
                    select(Restaurant.id).where(
                        Restaurant.organization_id == member.organization_id,
                        Restaurant.id.in_(ids),
                    )
                )
            ).all()
        )
        if ids != allowed:
            return False
        await self._session.execute(
            delete(RestaurantAssignment).where(
                RestaurantAssignment.membership_id == member.id
            )
        )
        self._session.add_all(
            [
                RestaurantAssignment(
                    membership_id=member.id,
                    organization_id=member.organization_id,
                    restaurant_id=id,
                )
                for id in sorted(ids)
            ]
        )
        return True
