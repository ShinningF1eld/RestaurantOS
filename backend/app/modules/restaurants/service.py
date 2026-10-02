"""Restaurant application service and command inputs."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.restaurants.repo.models import Restaurant
from app.modules.restaurants.repo.queries import RestaurantRepository
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.tenancy.access import AccessService
from app.modules.audit.service import record


from app.modules.restaurants.domain.commands import (
    CreateRestaurant as CreateRestaurant,
    UpdateRestaurant as UpdateRestaurant,
)


class RestaurantService:
    """Coordinates restaurant use cases and owns write transactions."""

    def __init__(
        self, session: AsyncSession, principal: AuthenticatedPrincipal
    ) -> None:
        self._session = session
        self._access = AccessService(session, principal)

    async def create(self, command: CreateRestaurant) -> Restaurant:
        """Create and return a restaurant atomically."""
        async with self._session.begin():
            context = await self._access.current(lock=True)
            context.require("restaurant.create")
            self._restaurants = RestaurantRepository(self._session, context)
            restaurant = Restaurant(
                organization_id=context.organization_id,
                name=command.name,
                address=command.address,
                phone=command.phone,
            )
            await self._restaurants.add(restaurant)
            await self._restaurants.flush()
            await self._restaurants.refresh(restaurant)
            record(
                self._session,
                context,
                "restaurant.created",
                "restaurant",
                restaurant.id,
                restaurant_id=restaurant.id,
            )
        return restaurant

    async def list_all(self) -> list[Restaurant]:
        """List restaurants."""
        context = await self._access.current()
        context.require("restaurant.read")
        return list(await RestaurantRepository(self._session, context).list_all())

    async def get(self, restaurant_id: int) -> Restaurant:
        """Get a restaurant or raise the public not-found domain error."""
        context = await self._access.current()
        await self._access.restaurant(context, restaurant_id, "restaurant.read")
        restaurant = await RestaurantRepository(self._session, context).get_by_id(
            restaurant_id
        )
        if restaurant is None:
            raise NotFoundError("Restaurant not found")
        return restaurant

    async def update(self, restaurant_id: int, command: UpdateRestaurant) -> Restaurant:
        """Apply supplied restaurant fields atomically."""
        async with self._session.begin():
            context = await self._access.current(lock=True)
            await self._access.restaurant(context, restaurant_id, "restaurant.update")
            self._restaurants = RestaurantRepository(self._session, context)
            restaurant = await self._restaurants.get_by_id(restaurant_id)
            if restaurant is None:
                raise NotFoundError("Restaurant not found")
            if "name" in command.fields:
                # Preserve the endpoint's existing behavior for an explicitly
                # supplied null name; the database remains authoritative for
                # rejecting a null value on this required column.
                setattr(restaurant, "name", command.name)
            if "address" in command.fields:
                restaurant.address = command.address
            if "phone" in command.fields:
                restaurant.phone = command.phone
            await self._restaurants.flush()
            await self._restaurants.refresh(restaurant)
            record(
                self._session,
                context,
                "restaurant.updated",
                "restaurant",
                restaurant.id,
                restaurant_id=restaurant.id,
                changes={"fields": sorted(command.fields)},
            )
        return restaurant

    async def delete(self, restaurant_id: int) -> None:
        """Delete a restaurant atomically."""
        async with self._session.begin():
            context = await self._access.current(lock=True)
            await self._access.restaurant(context, restaurant_id, "restaurant.delete")
            self._restaurants = RestaurantRepository(self._session, context)
            restaurant = await self._restaurants.get_by_id(restaurant_id)
            if restaurant is None:
                raise NotFoundError("Restaurant not found")
            # Audit resource ID is retained without a FK to the deleted restaurant.
            record(
                self._session,
                context,
                "restaurant.deleted",
                "restaurant",
                restaurant.id,
            )
            if await self._restaurants.has_dependents(restaurant_id):
                raise ConflictError(
                    "Restaurant has operational history; deletion is unavailable"
                )
            await self._restaurants.delete(restaurant)
