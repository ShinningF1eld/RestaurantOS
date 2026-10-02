"""HTTP endpoints for orders."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.modules.auth.dependencies import get_current_principal
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.orders.repo.models import Order
from app.modules.orders.schemas import (
    OrderCreate,
    OrderResponse,
    OrderUpdate,
    PaginatedOrders,
)
from app.modules.orders.service import (
    CreateOrder,
    OrderItemCommand,
    OrderService,
    UpdateOrder,
)


router = APIRouter(prefix="/api", tags=["orders"])


def _item_command(
    menu_item_id: int, quantity: int, notes: str | None
) -> OrderItemCommand:
    return OrderItemCommand(
        menu_item_id=menu_item_id,
        quantity=quantity,
        notes=notes,
    )


@router.post(
    "/restaurants/{restaurant_id}/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    restaurant_id: int,
    order_data: OrderCreate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Order:
    """Create an order from an HTTP request."""
    command = CreateOrder(
        table_number=order_data.table_number,
        customer_name=order_data.customer_name,
        notes=order_data.notes,
        items=tuple(
            _item_command(item.menu_item_id, item.quantity, item.notes)
            for item in order_data.items
        ),
    )
    return await OrderService(db, principal).create(restaurant_id, command)


@router.get(
    "/restaurants/{restaurant_id}/orders",
    response_model=PaginatedOrders,
)
async def get_restaurant_orders(
    restaurant_id: int,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> PaginatedOrders:
    """Return one page of a restaurant's orders."""
    page = await OrderService(db, principal).list_for_restaurant(
        restaurant_id, limit, offset
    )
    return PaginatedOrders.model_validate(
        {
            "items": page.items,
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        },
        from_attributes=True,
    )


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Order:
    """Return one order."""
    return await OrderService(db, principal).get(order_id)


@router.put("/orders/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: int,
    order_data: OrderUpdate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Order:
    """Apply an order update from an HTTP request."""
    items = (
        tuple(
            _item_command(item.menu_item_id, item.quantity, item.notes)
            for item in order_data.items
        )
        if order_data.items is not None
        else None
    )
    command = UpdateOrder(
        table_number=order_data.table_number,
        customer_name=order_data.customer_name,
        status=order_data.status,
        notes=order_data.notes,
        items=items,
        payment_status=order_data.payment_status,
        fields=frozenset(order_data.model_fields_set),
    )
    return await OrderService(db, principal).update(order_id, command)


@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: int,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete one order."""
    await OrderService(db, principal).delete(order_id)
