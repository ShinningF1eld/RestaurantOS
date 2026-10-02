from decimal import Decimal

from pydantic import BaseModel


class DashboardMetric(BaseModel):
    value: Decimal | int
    change_percent: Decimal


class SalesPoint(BaseModel):
    date: str
    sales: Decimal
    orders: int


class TopSellingItem(BaseModel):
    menu_item_id: int
    name: str
    quantity_sold: int
    sales: Decimal


class RestaurantDashboardAnalytics(BaseModel):
    sales: DashboardMetric
    orders: DashboardMetric
    average_order: DashboardMetric
    sales_graph: list[SalesPoint]
    top_selling_items: list[TopSellingItem]
