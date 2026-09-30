from collections.abc import Sequence
from decimal import Decimal
from types import TracebackType
from typing import Self, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.menu_items import MenuItem
from app.db.models.order import Order
from app.domain.order import OrderItemsLockedError
from app.services.order import (
    CreateOrder,
    OrderItemCommand,
    OrderService,
    UpdateOrder,
)


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self._session = session

    async def __aenter__(self) -> Self:
        self._session.events.append("transaction-entered")
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self._session.exit_exception_type = exception_type
        self._session.events.append("transaction-exited")
        return False


class FakeSession:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.exit_exception_type: type[BaseException] | None = None

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)


class FakeOrderRepository:
    def __init__(
        self,
        session: FakeSession,
        *,
        restaurant_exists: bool = True,
        menu_items: Sequence[MenuItem] = (),
        order: Order | None = None,
    ) -> None:
        self._session = session
        self._restaurant_exists = restaurant_exists
        self._menu_items = menu_items
        self.order = order
        self.added_order: Order | None = None
        self.deleted_order: Order | None = None

    async def restaurant_exists(self, restaurant_id: int) -> bool:
        self._session.events.append("restaurant-exists")
        return self._restaurant_exists

    async def get_by_id(self, order_id: int) -> Order | None:
        self._session.events.append("get-order")
        return self.order

    async def list_for_restaurant(
        self, restaurant_id: int, limit: int, offset: int
    ) -> Sequence[Order]:
        return ()

    async def count_for_restaurant(self, restaurant_id: int) -> int:
        return 0

    async def menu_items_for_restaurant(
        self, restaurant_id: int, menu_item_ids: Sequence[int]
    ) -> Sequence[MenuItem]:
        self._session.events.append("menu-items")
        return self._menu_items

    async def add(self, order: Order) -> None:
        self._session.events.append("add-order")
        self.added_order = order
        self.order = order

    async def delete(self, order: Order) -> None:
        self.deleted_order = order

    async def flush(self) -> None:
        self._session.events.append("flush")
        if self.order is not None and self.order.order_id is None:
            self.order.order_id = 1


def item(menu_item_id: int = 1, price: str = "12.50") -> MenuItem:
    return MenuItem(
        menu_item_id=menu_item_id,
        menu_id=1,
        name="Noodles",
        price=Decimal(price),
        is_available=True,
    )


@pytest.mark.asyncio
async def test_create_builds_price_snapshots_inside_one_transaction() -> None:
    session = FakeSession()
    repository = FakeOrderRepository(session, menu_items=[item()])
    service = OrderService(cast(AsyncSession, session), repository)

    order = await service.create(
        7,
        CreateOrder(
            table_number="A1",
            customer_name="Sam",
            notes=None,
            items=(OrderItemCommand(menu_item_id=1, quantity=2, notes="No chili"),),
        ),
    )

    assert session.events == [
        "transaction-entered",
        "restaurant-exists",
        "menu-items",
        "add-order",
        "flush",
        "get-order",
        "transaction-exited",
    ]
    assert order.subtotal == Decimal("25.00")
    assert order.total == Decimal("25.00")
    assert order.items[0].item_name == "Noodles"
    assert order.items[0].unit_price == Decimal("12.50")
    assert order.items[0].line_total == Decimal("25.00")


@pytest.mark.asyncio
async def test_failed_status_and_item_update_exits_transaction_with_error() -> None:
    session = FakeSession()
    existing_order = Order(
        order_id=4,
        restaurant_id=7,
        status="DRAFT",
        payment_status="UNPAID",
        subtotal=Decimal("12.50"),
        total=Decimal("12.50"),
        items=[],
    )
    repository = FakeOrderRepository(session, order=existing_order)
    service = OrderService(cast(AsyncSession, session), repository)

    with pytest.raises(OrderItemsLockedError):
        await service.update(
            4,
            UpdateOrder(
                table_number=None,
                customer_name=None,
                status="SUBMITTED",
                notes=None,
                items=(OrderItemCommand(menu_item_id=1, quantity=2, notes=None),),
                payment_status=None,
            ),
        )

    assert session.exit_exception_type is OrderItemsLockedError
    assert "flush" not in session.events
