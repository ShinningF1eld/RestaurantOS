"""Public tenancy interface consumed by other feature services."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.tenancy.domain.policies import AccessContext
from app.modules.tenancy.repo.access import (
    AccessRepository,
    restaurant_scope as restaurant_scope,
)


class AccessService:
    def __init__(
        self, session: AsyncSession, principal: AuthenticatedPrincipal
    ) -> None:
        self._principal = principal
        self._access = AccessRepository(session)

    async def current(self, *, lock: bool = False) -> AccessContext:
        return await self._access.current(self._principal, lock=lock)

    async def restaurant(
        self, context: AccessContext, restaurant_id: int, capability: str
    ) -> None:
        if not await self._access.restaurant_exists(context, restaurant_id):
            raise NotFoundError("Restaurant not found")
        context.require(capability)
