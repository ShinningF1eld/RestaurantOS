from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.repositories.analytics import AnalyticsRepository
from app.schemas.analytics import (
    DashboardMetric,
    RestaurantDashboardAnalytics,
    SalesPoint,
    TopSellingItem,
)
from app.services.analytics import AnalyticsService


router = APIRouter(
    prefix="/api",
    tags=["analytics"],
)


def get_analytics_service(
    db: AsyncSession = Depends(get_db),
) -> AnalyticsService:
    return AnalyticsService(AnalyticsRepository(db))


@router.get(
    "/restaurants/{restaurant_id}/analytics/dashboard",
    response_model=RestaurantDashboardAnalytics,
)
async def get_restaurant_dashboard_analytics(
    restaurant_id: int,
    service: AnalyticsService = Depends(get_analytics_service),
) -> RestaurantDashboardAnalytics:
    data = await service.get_restaurant_dashboard_analytics(restaurant_id)
    return RestaurantDashboardAnalytics(
        sales=DashboardMetric(
            value=data.sales.value,
            change_percent=data.sales.change_percent,
        ),
        orders=DashboardMetric(
            value=data.orders.value,
            change_percent=data.orders.change_percent,
        ),
        average_order=DashboardMetric(
            value=data.average_order.value,
            change_percent=data.average_order.change_percent,
        ),
        sales_graph=[
            SalesPoint(
                date=point.date,
                sales=point.sales,
                orders=point.orders,
            )
            for point in data.sales_graph
        ],
        top_selling_items=[
            TopSellingItem(
                menu_item_id=item.menu_item_id,
                name=item.name,
                quantity_sold=item.quantity_sold,
                sales=item.sales,
            )
            for item in data.top_selling_items
        ],
    )
