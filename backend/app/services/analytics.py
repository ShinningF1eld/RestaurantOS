"""Application service for restaurant dashboard analytics."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Protocol

from app.core.errors import NotFoundError
from app.repositories.analytics import (
    CompletedTotals,
    SalesGraphRow,
    TopSellingItemRow,
)


@dataclass(frozen=True, slots=True)
class DashboardMetricData:
    value: Decimal | int
    change_percent: Decimal


@dataclass(frozen=True, slots=True)
class SalesPointData:
    date: str
    sales: Decimal
    orders: int


@dataclass(frozen=True, slots=True)
class TopSellingItemData:
    menu_item_id: int
    name: str
    quantity_sold: int
    sales: Decimal


@dataclass(frozen=True, slots=True)
class RestaurantDashboardAnalyticsData:
    sales: DashboardMetricData
    orders: DashboardMetricData
    average_order: DashboardMetricData
    sales_graph: list[SalesPointData]
    top_selling_items: list[TopSellingItemData]


class AnalyticsRepositoryPort(Protocol):
    """Typed persistence boundary consumed by the dashboard use case."""

    async def restaurant_exists(self, restaurant_id: int) -> bool: ...

    async def get_completed_totals(
        self,
        restaurant_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> CompletedTotals: ...

    async def get_sales_graph(
        self,
        restaurant_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> list[SalesGraphRow]: ...

    async def get_top_selling_items(
        self,
        restaurant_id: int,
        start_at: datetime,
        end_at: datetime,
        *,
        limit: int = 5,
    ) -> list[TopSellingItemRow]: ...


def start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min)


def end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max)


def percent_change(current: Decimal | int, previous: Decimal | int) -> Decimal:
    current_value = Decimal(str(current))
    previous_value = Decimal(str(previous))

    if previous_value == 0:
        return Decimal("0.00")

    return ((current_value - previous_value) / previous_value * 100).quantize(
        Decimal("0.01")
    )


class AnalyticsService:
    """Coordinate dashboard queries and calculate presentation-ready values."""

    def __init__(self, repository: AnalyticsRepositoryPort) -> None:
        self._repository = repository

    async def get_restaurant_dashboard_analytics(
        self,
        restaurant_id: int,
        *,
        today: date | None = None,
    ) -> RestaurantDashboardAnalyticsData:
        if not await self._repository.restaurant_exists(restaurant_id):
            raise NotFoundError("Restaurant not found")

        report_date = today if today is not None else date.today()
        yesterday = report_date - timedelta(days=1)

        today_totals = await self._repository.get_completed_totals(
            restaurant_id,
            start_of_day(report_date),
            end_of_day(report_date),
        )
        yesterday_totals = await self._repository.get_completed_totals(
            restaurant_id,
            start_of_day(yesterday),
            end_of_day(yesterday),
        )

        today_average_order = (
            today_totals.sales / today_totals.order_count
            if today_totals.order_count > 0
            else Decimal("0.00")
        )
        yesterday_average_order = (
            yesterday_totals.sales / yesterday_totals.order_count
            if yesterday_totals.order_count > 0
            else Decimal("0.00")
        )

        graph_start = report_date - timedelta(days=6)
        graph_rows = await self._repository.get_sales_graph(
            restaurant_id,
            start_of_day(graph_start),
            end_of_day(report_date),
        )
        graph_by_date = {row.date: row for row in graph_rows}
        sales_graph: list[SalesPointData] = []
        for offset in range(7):
            graph_date = graph_start + timedelta(days=offset)
            graph_key = graph_date.isoformat()
            row = graph_by_date.get(graph_key)
            sales_graph.append(
                SalesPointData(
                    date=graph_key,
                    sales=row.sales if row else Decimal("0.00"),
                    orders=row.order_count if row else 0,
                )
            )

        top_item_rows = await self._repository.get_top_selling_items(
            restaurant_id,
            start_of_day(graph_start),
            end_of_day(report_date),
        )
        top_selling_items = [
            TopSellingItemData(
                menu_item_id=row.menu_item_id or 0,
                name=row.name,
                quantity_sold=row.quantity_sold,
                sales=row.sales,
            )
            for row in top_item_rows
        ]

        return RestaurantDashboardAnalyticsData(
            sales=DashboardMetricData(
                value=today_totals.sales,
                change_percent=percent_change(
                    today_totals.sales, yesterday_totals.sales
                ),
            ),
            orders=DashboardMetricData(
                value=today_totals.order_count,
                change_percent=percent_change(
                    today_totals.order_count, yesterday_totals.order_count
                ),
            ),
            average_order=DashboardMetricData(
                value=today_average_order.quantize(Decimal("0.01")),
                change_percent=percent_change(
                    today_average_order, yesterday_average_order
                ),
            ),
            sales_graph=sales_graph,
            top_selling_items=top_selling_items,
        )
