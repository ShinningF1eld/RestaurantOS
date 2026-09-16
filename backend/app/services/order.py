"""Order application service and framework-independent command inputs."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.db.models.menu_items import MenuItem
from app.db.models.order import Order, OrderItem
from app.domain.order import (
    ensure_order_items_mutable,
    ensure_valid_order_transition,
    ensure_valid_payment_status,
)
from app.repositories.order import OrderRepository


@dataclass(frozen=True, slots=True)
class OrderItemCommand:
    """An order-item input independent of HTTP schemas and persistence."""

    menu_item_id: int
    quantity: int
    notes: str | None


@dataclass(frozen=True, slots=True)
class CreateOrder:
    """Input for creating an order."""

    table_number: str | None
    customer_name: str | None
    notes: str | None
    items: tuple[OrderItemCommand, ...]


@dataclass(frozen=True, slots=True)
class UpdateOrder:
    """Supplied mutable fields for an order update."""

    table_number: str | None
    customer_name: str | None
    status: str | None
    notes: str | None
    items: tuple[OrderItemCommand, ...] | None
    payment_status: str | None


@dataclass(frozen=True, slots=True)
class OrderPage:
    """A typed order-list result independent of API response schemas."""

    items: tuple[Order, ...]
    total: int
    limit: int
    offset: int


class OrderRepositoryProtocol(Protocol):
    """Persistence operations required by ``OrderService``."""

    async def restaurant_exists(self, restaurant_id: int) -> bool: ...

    async def get_by_id(self, order_id: int) -> Order | None: ...

    async def list_for_restaurant(
        self, restaurant_id: int, limit: int, offset: int
    ) -> Sequence[Order]: ...

    async def count_for_restaurant(self, restaurant_id: int) -> int: ...

    async def menu_items_for_restaurant(
        self, restaurant_id: int, menu_item_ids: Sequence[int]
    ) -> Sequence[MenuItem]: ...

    async def add(self, order: Order) -> None: ...

    async def delete(self, order: Order) -> None: ...

    async def flush(self) -> None: ...


class OrderService:
    """Coordinates order use cases and owns every order write transaction."""

    def __init__(
        self,
        session: AsyncSession,
        repository: OrderRepositoryProtocol | None = None,
    ) -> None:
        self._session = session
        self._orders = repository or OrderRepository(session)

    async def create(self, restaurant_id: int, command: CreateOrder) -> Order:
        """Create an order, its item snapshots, and totals atomically."""
        async with self._session.begin():
            if not await self._orders.restaurant_exists(restaurant_id):
                raise NotFoundError("Restaurant not found")
            order_items, subtotal = await self._build_order_items(
                restaurant_id, command.items
            )
            order = Order(
                restaurant_id=restaurant_id,
                table_number=command.table_number,
                customer_name=command.customer_name,
                notes=command.notes,
                subtotal=subtotal,
                total=subtotal,
                items=order_items,
            )
            await self._orders.add(order)
            await self._orders.flush()
            return await self._get_order_or_error(order.order_id)

    async def get(self, order_id: int) -> Order:
        """Return one fully loaded order."""
        return await self._get_order_or_error(order_id)

    async def list_for_restaurant(
        self, restaurant_id: int, limit: int, offset: int
    ) -> OrderPage:
        """Return a restaurant's order page or its established not-found error."""
        if not await self._orders.restaurant_exists(restaurant_id):
            raise NotFoundError("Restaurant not found")
        total = await self._orders.count_for_restaurant(restaurant_id)
        orders = await self._orders.list_for_restaurant(restaurant_id, limit, offset)
        return OrderPage(tuple(orders), total, limit, offset)

    async def update(self, order_id: int, command: UpdateOrder) -> Order:
        """Apply supplied order fields atomically, including item replacement."""
        async with self._session.begin():
            order = await self._get_order_or_error(order_id)
            if command.status is not None:
                order.status = ensure_valid_order_transition(order.status, command.status)
            if command.payment_status is not None:
                order.payment_status = ensure_valid_payment_status(command.payment_status)
            if command.table_number is not None:
                order.table_number = command.table_number
            if command.customer_name is not None:
                order.customer_name = command.customer_name
            if command.notes is not None:
                order.notes = command.notes
            if command.items is not None:
                ensure_order_items_mutable(order.status)
                order_items, subtotal = await self._build_order_items(
                    order.restaurant_id, command.items
                )
                order.items = order_items
                order.subtotal = subtotal
                order.total = subtotal
            await self._orders.flush()
            return await self._get_order_or_error(order_id)

    async def delete(self, order_id: int) -> None:
        """Delete an order atomically."""
        async with self._session.begin():
            order = await self._get_order_or_error(order_id)
            await self._orders.delete(order)

    async def _get_order_or_error(self, order_id: int) -> Order:
        order = await self._orders.get_by_id(order_id)
        if order is None:
            raise NotFoundError("Order not found")
        return order

    async def _build_order_items(
        self, restaurant_id: int, item_commands: Sequence[OrderItemCommand]
    ) -> tuple[list[OrderItem], Decimal]:
        menu_item_ids = [item.menu_item_id for item in item_commands]
        menu_items = await self._orders.menu_items_for_restaurant(
            restaurant_id, menu_item_ids
        )
        by_id = {menu_item.menu_item_id: menu_item for menu_item in menu_items}
        missing_items = [
            menu_item_id
            for menu_item_id in menu_item_ids
            if menu_item_id not in by_id
        ]
        if missing_items:
            raise NotFoundError(
                f"Menu items not found for restaurant: {missing_items}"
            )
        unavailable_items = [
            menu_item.menu_item_id
            for menu_item in by_id.values()
            if not menu_item.is_available
        ]
        if unavailable_items:
            raise ValidationError(f"Menu items are unavailable: {unavailable_items}")

        subtotal = Decimal("0.00")
        order_items: list[OrderItem] = []
        for item_command in item_commands:
            menu_item = by_id[item_command.menu_item_id]
            line_total = menu_item.price * item_command.quantity
            subtotal += line_total
            order_items.append(
                OrderItem(
                    menu_item_id=menu_item.menu_item_id,
                    item_name=menu_item.name,
                    quantity=item_command.quantity,
                    unit_price=menu_item.price,
                    line_total=line_total,
                    notes=item_command.notes,
                )
            )
        return order_items, subtotal
