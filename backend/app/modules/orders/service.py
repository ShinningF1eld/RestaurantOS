"""Order application service and framework-independent command inputs."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.tenancy.access import AccessService
from app.modules.tenancy.domain.policies import AccessContext, authorize_order_update
from app.modules.audit.service import record
from app.modules.catalog.repo.models import MenuItem
from app.modules.orders.repo.models import Order, OrderItem
from app.modules.orders.domain.policies import (
    ensure_order_items_mutable,
    ensure_valid_order_transition,
    ensure_valid_payment_status,
)
from app.modules.orders.repo.queries import OrderRepository


from app.modules.orders.domain.commands import (
    OrderItemCommand as OrderItemCommand,
    CreateOrder as CreateOrder,
    UpdateOrder as UpdateOrder,
)


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

    async def get_by_id(self, order_id: int, *, lock: bool = False) -> Order | None: ...

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
        principal: AuthenticatedPrincipal,
        repository: OrderRepositoryProtocol | None = None,
    ) -> None:
        self._session = session
        self._repository = repository
        self._access = AccessService(session, principal)

    async def _prepare(self, *, lock: bool = False) -> AccessContext:
        context = await self._access.current(lock=lock)
        self._orders = self._repository or OrderRepository(self._session, context)
        return context

    async def create(self, restaurant_id: int, command: CreateOrder) -> Order:
        """Create an order, its item snapshots, and totals atomically."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            await self._access.restaurant(context, restaurant_id, "order.create")
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
            result = await self._get_order_or_error(order.order_id)
            record(
                self._session,
                context,
                "order.created",
                "order",
                order.order_id,
                restaurant_id=restaurant_id,
                changes={"total": str(order.total)},
            )
            return result

    async def get(self, order_id: int) -> Order:
        """Return one fully loaded order."""
        context = await self._prepare()
        context.require("order.read")
        return await self._get_order_or_error(order_id)

    async def list_for_restaurant(
        self, restaurant_id: int, limit: int, offset: int
    ) -> OrderPage:
        """Return a restaurant's order page or its established not-found error."""
        context = await self._prepare()
        await self._access.restaurant(context, restaurant_id, "order.read")
        if not await self._orders.restaurant_exists(restaurant_id):
            raise NotFoundError("Restaurant not found")
        total = await self._orders.count_for_restaurant(restaurant_id)
        orders = await self._orders.list_for_restaurant(restaurant_id, limit, offset)
        return OrderPage(tuple(orders), total, limit, offset)

    async def update(self, order_id: int, command: UpdateOrder) -> Order:
        """Apply supplied order fields atomically, including item replacement."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            order = await self._get_order_or_error(order_id, lock=True)
            authorize_order_update(
                context, command.fields, order.status, command.status
            )
            if command.status is not None:
                order.status = ensure_valid_order_transition(
                    order.status, command.status
                )
            if command.payment_status is not None:
                order.payment_status = ensure_valid_payment_status(
                    command.payment_status
                )
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
            result = await self._get_order_or_error(order_id)
            record(
                self._session,
                context,
                "order.updated",
                "order",
                order_id,
                restaurant_id=order.restaurant_id,
                changes={
                    "fields": sorted(command.fields),
                    "status": order.status,
                    "payment_status": order.payment_status,
                    "total": str(order.total),
                },
            )
            return result

    async def delete(self, order_id: int) -> None:
        """Delete an order atomically."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            order = await self._get_order_or_error(order_id, lock=True)
            context.require("order.delete")
            record(
                self._session,
                context,
                "order.deleted",
                "order",
                order_id,
                restaurant_id=order.restaurant_id,
                changes={"status": order.status, "total": str(order.total)},
            )
            await self._orders.delete(order)

    async def _get_order_or_error(self, order_id: int, *, lock: bool = False) -> Order:
        order = await self._orders.get_by_id(order_id, lock=lock)
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
            menu_item_id for menu_item_id in menu_item_ids if menu_item_id not in by_id
        ]
        if missing_items:
            raise NotFoundError(f"Menu items not found for restaurant: {missing_items}")
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
