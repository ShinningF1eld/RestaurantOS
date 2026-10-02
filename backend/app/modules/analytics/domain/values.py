"""Feature-owned value and command inputs independent of HTTP and persistence."""

from dataclasses import dataclass
from decimal import Decimal


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
