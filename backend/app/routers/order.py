from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.db.models.menu import Menu
from app.db.models.menu_items import MenuItem
from app.db.models.order import Order, OrderItem
from app.db.models.restaurant import Restaurant
from app.schemas.order import OrderCreate, OrderResponse, OrderUpdate, PaginatedOrders


router = APIRouter(
    prefix="/api",
    tags=["orders"],
)

ORDER_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"SUBMITTED", "CANCELLED"},
    "SUBMITTED": {"ACCEPTED", "CANCELLED"},
    "ACCEPTED": {"PREPARING", "CANCELLED"},
    "PREPARING": {"READY", "CANCELLED"},
    "READY": {"COMPLETED", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}
PAYMENT_STATUSES = {"UNPAID", "PAID", "VOID"}


def normalize_status(value: str) -> str:
    # The initial UI used lower-case values. Keep clients comprehensible while
    # storing one canonical representation.
    aliases = {"PENDING": "DRAFT", "COMPLETE": "COMPLETED", "CANCELLED": "CANCELLED"}
    normalized = value.strip().upper()
    return aliases.get(normalized, normalized)


def ensure_valid_transition(current: str, requested: str) -> str:
    requested = normalize_status(requested)
    current = normalize_status(current)
    if requested == current:
        return requested
    if requested not in ORDER_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid order status transition from {current} to {requested}",
        )
    return requested


async def get_order_or_404(
    order_id: int,
    db: AsyncSession,
) -> Order:
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.menu_item)
        )
        .where(Order.order_id == order_id)
    )

    order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    return order


async def build_order_items(
    restaurant_id: int,
    order_data: OrderCreate | OrderUpdate,
    db: AsyncSession,
) -> tuple[list[OrderItem], Decimal]:
    menu_item_ids = [
        item.menu_item_id
        for item in order_data.items or []
    ]

    result = await db.execute(
        select(MenuItem)
        .join(Menu)
        .where(
            Menu.restaurant_id == restaurant_id,
            MenuItem.menu_item_id.in_(menu_item_ids),
        )
    )

    menu_items = {
        item.menu_item_id: item
        for item in result.scalars().all()
    }

    missing_items = [
        menu_item_id
        for menu_item_id in menu_item_ids
        if menu_item_id not in menu_items
    ]

    if missing_items:
        raise HTTPException(
            status_code=404,
            detail=f"Menu items not found for restaurant: {missing_items}",
        )

    unavailable_items = [item.menu_item_id for item in menu_items.values() if not item.is_available]
    if unavailable_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Menu items are unavailable: {unavailable_items}",
        )

    order_items = []
    subtotal = Decimal("0.00")

    for item_data in order_data.items or []:
        menu_item = menu_items[item_data.menu_item_id]
        unit_price = menu_item.price
        line_total = unit_price * item_data.quantity
        subtotal += line_total

        order_items.append(
            OrderItem(
                menu_item_id=item_data.menu_item_id,
                item_name=menu_item.name,
                quantity=item_data.quantity,
                unit_price=unit_price,
                line_total=line_total,
                notes=item_data.notes,
            )
        )

    return order_items, subtotal


@router.post(
    "/restaurants/{restaurant_id}/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    restaurant_id: int,
    order_data: OrderCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Restaurant).where(
            Restaurant.id == restaurant_id
        )
    )

    restaurant = result.scalar_one_or_none()

    if restaurant is None:
        raise HTTPException(
            status_code=404,
            detail="Restaurant not found",
        )

    order_items, subtotal = await build_order_items(
        restaurant_id,
        order_data,
        db,
    )

    order = Order(
        restaurant_id=restaurant_id,
        table_number=order_data.table_number,
        customer_name=order_data.customer_name,
        notes=order_data.notes,
        subtotal=subtotal,
        total=subtotal,
        items=order_items,
    )

    db.add(order)
    await db.commit()

    return await get_order_or_404(order.order_id, db)


@router.get(
    "/restaurants/{restaurant_id}/orders",
    response_model=PaginatedOrders,
)
async def get_restaurant_orders(
    restaurant_id: int,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    restaurant_result = await db.execute(select(Restaurant.id).where(Restaurant.id == restaurant_id))
    if restaurant_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    total = await db.scalar(select(func.count(Order.order_id)).where(Order.restaurant_id == restaurant_id))
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.menu_item)
        )
        .where(Order.restaurant_id == restaurant_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return PaginatedOrders(items=result.scalars().all(), total=total or 0, limit=limit, offset=offset)


@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await get_order_or_404(order_id, db)


@router.put(
    "/orders/{order_id}",
    response_model=OrderResponse,
)
async def update_order(
    order_id: int,
    order_data: OrderUpdate,
    db: AsyncSession = Depends(get_db),
):
    order = await get_order_or_404(order_id, db)

    update_data = order_data.model_dump(
        exclude_unset=True,
        exclude={"items"},
    )

    for field, value in update_data.items():
        if field == "status" and value is not None:
            order.status = ensure_valid_transition(order.status, value)
        elif field == "payment_status" and value is not None:
            normalized_payment_status = value.strip().upper()
            if normalized_payment_status not in PAYMENT_STATUSES:
                raise HTTPException(status_code=422, detail="Invalid payment status")
            order.payment_status = normalized_payment_status
        elif value is not None:
            setattr(order, field, value)

    if order_data.items is not None:
        if normalize_status(order.status) != "DRAFT":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order items can only be changed while an order is in DRAFT",
            )
        order_items, subtotal = await build_order_items(
            order.restaurant_id,
            order_data,
            db,
        )

        order.items = order_items
        order.subtotal = subtotal
        order.total = subtotal

    await db.commit()

    return await get_order_or_404(order_id, db)


@router.delete(
    "/orders/{order_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
):
    order = await get_order_or_404(order_id, db)

    await db.delete(order)
    await db.commit()
