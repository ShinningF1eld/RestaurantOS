"""Fresh membership reads and reusable predicates for tenant-scoped SQL."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ForbiddenError
from app.modules.restaurants.repo.models import Restaurant
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.tenancy.domain.policies import AccessContext
from app.modules.tenancy.repo.models import (
    Membership,
    Organization,
    RestaurantAssignment,
)


def restaurant_scope(context: AccessContext) -> ColumnElement[bool]:
    predicate = Restaurant.organization_id == context.organization_id
    if context.role.value != "OWNER":
        predicate = predicate & Restaurant.id.in_(context.restaurant_ids)
    return predicate


class AccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def current(
        self, principal: AuthenticatedPrincipal, *, lock: bool = False
    ) -> AccessContext:
        statement = (
            select(Membership, Organization.number)
            .join(Organization)
            .where(
                Membership.user_id == principal.id,
                Membership.status == "active",
                Organization.status == "active",
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update(read=True, of=Membership)
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            raise ForbiddenError("Active organization membership required")
        membership, number = row
        assignments = select(RestaurantAssignment.restaurant_id).where(
            RestaurantAssignment.membership_id == membership.id,
            RestaurantAssignment.organization_id == membership.organization_id,
        )
        if lock:
            assignments = assignments.with_for_update(read=True)
        restaurants = frozenset((await self._session.scalars(assignments)).all())
        return AccessContext(
            principal.id,
            membership.id,
            membership.organization_id,
            number,
            membership.role,
            restaurants,
        )

    async def restaurant_exists(
        self, context: AccessContext, restaurant_id: int
    ) -> bool:
        return (
            await self._session.scalar(
                select(Restaurant.id).where(
                    Restaurant.id == restaurant_id, restaurant_scope(context)
                )
            )
            is not None
        )
