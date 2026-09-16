"""Restaurant application service and command inputs."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models.restaurant import Restaurant
from app.repositories.restaurant import RestaurantRepository


@dataclass(frozen=True, slots=True)
class CreateRestaurant:
    name: str
    address: str | None
    phone: str | None


@dataclass(frozen=True, slots=True)
class UpdateRestaurant:
    name: str | None
    address: str | None
    phone: str | None
    fields: frozenset[str]


class RestaurantService:
    """Coordinates restaurant use cases and owns write transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._restaurants = RestaurantRepository(session)

    async def create(self, command: CreateRestaurant) -> Restaurant:
        """Create and return a restaurant atomically."""
        async with self._session.begin():
            restaurant = Restaurant(
                name=command.name,
                address=command.address,
                phone=command.phone,
            )
            await self._restaurants.add(restaurant)
            await self._restaurants.flush()
            await self._restaurants.refresh(restaurant)
        return restaurant

    async def list_all(self) -> list[Restaurant]:
        """List restaurants."""
        return list(await self._restaurants.list_all())

    async def get(self, restaurant_id: int) -> Restaurant:
        """Get a restaurant or raise the public not-found domain error."""
        restaurant = await self._restaurants.get_by_id(restaurant_id)
        if restaurant is None:
            raise NotFoundError("Restaurant not found")
        return restaurant

    async def update(
        self, restaurant_id: int, command: UpdateRestaurant
    ) -> Restaurant:
        """Apply supplied restaurant fields atomically."""
        async with self._session.begin():
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
        return restaurant

    async def delete(self, restaurant_id: int) -> None:
        """Delete a restaurant atomically."""
        async with self._session.begin():
            restaurant = await self._restaurants.get_by_id(restaurant_id)
            if restaurant is None:
                raise NotFoundError("Restaurant not found")
            await self._restaurants.delete(restaurant)
