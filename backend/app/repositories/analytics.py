"""Persistence queries used by the restaurant analytics dashboard."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.order import Order, OrderItem
from app.db.models.restaurant import Restaurant


@dataclass(frozen=True, slots=True)
class CompletedTotals:
    """Completed-order aggregate for one restaurant and time window."""

    sales: Decimal
    order_count: int


@dataclass(frozen=True, slots=True)
class SalesGraphRow:
    """Completed-order aggregate for one calendar date."""

    date: str
    sales: Decimal
    order_count: int


@dataclass(frozen=True, slots=True)
class TopSellingItemRow:
    """Sales aggregate for one snapshotted order item."""

    menu_item_id: int | None
    name: str
    quantity_sold: int
    sales: Decimal


class AnalyticsRepository:
    """Run explicit, read-only analytics queries for an async session.

    This repository intentionally does not commit or roll back. Dashboard
    requests are read-only and the request-owned session is closed by the
    database dependency.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def restaurant_exists(self, restaurant_id: int) -> bool:
        result = await self._session.execute(
            select(Restaurant.id).where(Restaurant.id == restaurant_id)
        )
        return result.scalar_one_or_none() is not None

    async def get_completed_totals(
        self,
        restaurant_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> CompletedTotals:
        result = await self._session.execute(
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
        return CompletedTotals(
            sales=Decimal(str(sales)),
            order_count=int(order_count),
        )

    async def get_sales_graph(
        self,
        restaurant_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> list[SalesGraphRow]:
        result = await self._session.execute(
            select(
                func.date(Order.created_at).label("order_date"),
                func.coalesce(func.sum(Order.total), 0).label("sales"),
                func.count(Order.order_id).label("orders"),
            )
            .where(
                Order.restaurant_id == restaurant_id,
                Order.status == "COMPLETED",
                Order.created_at >= start_at,
                Order.created_at <= end_at,
            )
            .group_by(func.date(Order.created_at))
        )
        return [
            SalesGraphRow(
                date=str(row.order_date),
                sales=Decimal(str(row.sales)),
                order_count=int(row.orders),
            )
            for row in result.all()
        ]

    async def get_top_selling_items(
        self,
        restaurant_id: int,
        start_at: datetime,
        end_at: datetime,
        *,
        limit: int = 5,
    ) -> list[TopSellingItemRow]:
        result = await self._session.execute(
            select(
                OrderItem.menu_item_id,
                OrderItem.item_name,
                func.coalesce(func.sum(OrderItem.quantity), 0).label(
                    "quantity_sold"
                ),
                func.coalesce(func.sum(OrderItem.line_total), 0).label("sales"),
            )
            .join(Order, Order.order_id == OrderItem.order_id)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.status == "COMPLETED",
                Order.created_at >= start_at,
                Order.created_at <= end_at,
            )
            .group_by(OrderItem.menu_item_id, OrderItem.item_name)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(limit)
        )
        return [
            TopSellingItemRow(
                menu_item_id=row.menu_item_id,
                name=row.item_name,
                quantity_sold=int(row.quantity_sold),
                sales=Decimal(str(row.sales)),
            )
            for row in result.all()
        ]
