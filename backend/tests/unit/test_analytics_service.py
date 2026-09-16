from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.errors import NotFoundError
from app.repositories.analytics import (
    CompletedTotals,
    SalesGraphRow,
    TopSellingItemRow,
)
from app.services.analytics import AnalyticsService


class FakeAnalyticsRepository:
    def __init__(self, *, exists: bool = True) -> None:
        self.exists = exists
        self.totals = [
            CompletedTotals(Decimal("240.00"), 2),
            CompletedTotals(Decimal("120.00"), 1),
        ]
        self.graph = [
            SalesGraphRow("2026-09-12", Decimal("50.00"), 1),
            SalesGraphRow("2026-09-16", Decimal("240.00"), 2),
        ]
        self.items = [
            TopSellingItemRow(None, "Historic item", 3, Decimal("30.00")),
            TopSellingItemRow(12, "Pad Thai", 2, Decimal("240.00")),
        ]
        self.windows: list[tuple[datetime, datetime]] = []

    async def restaurant_exists(self, restaurant_id: int) -> bool:
        return self.exists

    async def get_completed_totals(
        self,
        restaurant_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> CompletedTotals:
        self.windows.append((start_at, end_at))
        return self.totals.pop(0)

    async def get_sales_graph(
        self,
        restaurant_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> list[SalesGraphRow]:
        self.windows.append((start_at, end_at))
        return self.graph

    async def get_top_selling_items(
        self,
        restaurant_id: int,
        start_at: datetime,
        end_at: datetime,
        *,
        limit: int = 5,
    ) -> list[TopSellingItemRow]:
        self.windows.append((start_at, end_at))
        assert limit == 5
        return self.items


@pytest.mark.asyncio
async def test_dashboard_service_calculates_metrics_and_seven_day_window() -> None:
    repository = FakeAnalyticsRepository()
    service = AnalyticsService(repository)

    result = await service.get_restaurant_dashboard_analytics(
        7,
        today=date(2026, 9, 16),
    )

    assert result.sales.value == Decimal("240.00")
    assert result.sales.change_percent == Decimal("100.00")
    assert result.orders.value == 2
    assert result.orders.change_percent == Decimal("100.00")
    assert result.average_order.value == Decimal("120.00")
    assert result.average_order.change_percent == Decimal("0.00")
    assert [point.date for point in result.sales_graph] == [
        "2026-09-10",
        "2026-09-11",
        "2026-09-12",
        "2026-09-13",
        "2026-09-14",
        "2026-09-15",
        "2026-09-16",
    ]
    assert result.sales_graph[2].sales == Decimal("50.00")
    assert result.sales_graph[-1].orders == 2
    assert result.top_selling_items[0].menu_item_id == 0
    assert result.top_selling_items[0].name == "Historic item"
    assert repository.windows[0] == (
        datetime(2026, 9, 16),
        datetime(2026, 9, 16, 23, 59, 59, 999999),
    )


@pytest.mark.asyncio
async def test_dashboard_service_raises_typed_error_for_missing_restaurant() -> None:
    repository = FakeAnalyticsRepository(exists=False)
    service = AnalyticsService(repository)

    with pytest.raises(NotFoundError, match="Restaurant not found"):
        await service.get_restaurant_dashboard_analytics(
            404,
            today=date(2026, 9, 16),
        )
