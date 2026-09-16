from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models.order import Order, OrderItem
from app.db.models.restaurant import Restaurant
from app.schemas.analytics import (
    DashboardMetric,
    RestaurantDashboardAnalytics,
    SalesPoint,
    TopSellingItem,
)


router = APIRouter(
    prefix="/api",
    tags=["analytics"],
)


def start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min)


def end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max)


def percent_change(
    current: Decimal | int,
    previous: Decimal | int,
) -> Decimal:
    current_value = Decimal(str(current))
    previous_value = Decimal(str(previous))

    if previous_value == 0:
        return Decimal("0.00")

    return ((current_value - previous_value) / previous_value * 100).quantize(
        Decimal("0.01")
    )


async def get_completed_totals(
    restaurant_id: int,
    start_at: datetime,
    end_at: datetime,
    db: AsyncSession,
) -> tuple[Decimal, int]:
    result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0),
            func.count(Order.order_id),
        ).where(
            Order.restaurant_id == restaurant_id,
            Order.status == "COMPLETED",
            Order.created_at >= start_at,
            Order.created_at <= end_at,
        )
    )

    sales, order_count = result.one()

    return Decimal(str(sales)), int(order_count)


@router.get(
    "/restaurants/{restaurant_id}/analytics/dashboard",
    response_model=RestaurantDashboardAnalytics,
)
async def get_restaurant_dashboard_analytics(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db),
):
    restaurant_result = await db.execute(
        select(Restaurant.id).where(
            Restaurant.id == restaurant_id
        )
    )

    if restaurant_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=404,
            detail="Restaurant not found",
        )

    today = date.today()
    yesterday = today - timedelta(days=1)

    today_sales, today_orders = await get_completed_totals(
        restaurant_id,
        start_of_day(today),
        end_of_day(today),
        db,
    )

    yesterday_sales, yesterday_orders = await get_completed_totals(
        restaurant_id,
        start_of_day(yesterday),
        end_of_day(yesterday),
        db,
    )

    today_average_order = (
        today_sales / today_orders
        if today_orders > 0
        else Decimal("0.00")
    )
    yesterday_average_order = (
        yesterday_sales / yesterday_orders
        if yesterday_orders > 0
        else Decimal("0.00")
    )

    graph_start = today - timedelta(days=6)
    graph_result = await db.execute(
        select(
            func.date(Order.created_at).label("order_date"),
            func.coalesce(func.sum(Order.total), 0).label("sales"),
            func.count(Order.order_id).label("orders"),
        )
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status == "COMPLETED",
            Order.created_at >= start_of_day(graph_start),
            Order.created_at <= end_of_day(today),
        )
        .group_by(func.date(Order.created_at))
    )

    graph_by_date = {
        str(row.order_date): row
        for row in graph_result.all()
    }

    sales_graph = []

    for offset in range(7):
        graph_date = graph_start + timedelta(days=offset)
        graph_key = graph_date.isoformat()
        row = graph_by_date.get(graph_key)

        sales_graph.append(
            SalesPoint(
                date=graph_key,
                sales=Decimal(str(row.sales)) if row else Decimal("0.00"),
                orders=int(row.orders) if row else 0,
            )
        )

    top_items_result = await db.execute(
        select(
            OrderItem.menu_item_id,
            OrderItem.item_name,
            func.coalesce(func.sum(OrderItem.quantity), 0).label("quantity_sold"),
            func.coalesce(func.sum(OrderItem.line_total), 0).label("sales"),
        )
        .join(Order, Order.order_id == OrderItem.order_id)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status == "COMPLETED",
            Order.created_at >= start_of_day(graph_start),
            Order.created_at <= end_of_day(today),
        )
        .group_by(OrderItem.menu_item_id, OrderItem.item_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
    )

    top_selling_items = [
        TopSellingItem(
            menu_item_id=row.menu_item_id or 0,
            name=row.item_name,
            quantity_sold=int(row.quantity_sold),
            sales=Decimal(str(row.sales)),
        )
        for row in top_items_result.all()
    ]

    return RestaurantDashboardAnalytics(
        sales=DashboardMetric(
            value=today_sales,
            change_percent=percent_change(today_sales, yesterday_sales),
        ),
        orders=DashboardMetric(
            value=today_orders,
            change_percent=percent_change(today_orders, yesterday_orders),
        ),
        average_order=DashboardMetric(
            value=today_average_order.quantize(Decimal("0.01")),
            change_percent=percent_change(
                today_average_order,
                yesterday_average_order,
            ),
        ),
        sales_graph=sales_graph,
        top_selling_items=top_selling_items,
    )
