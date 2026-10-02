from datetime import datetime
from decimal import Decimal

import pytest

from app.db.database import AsyncSessionLocal
from app.db.models.order import Order, OrderItem
from app.db.models.restaurant import Restaurant
from app.modules.analytics.service import AnalyticsService


@pytest.mark.asyncio
async def test_analytics_queries_count_completed_orders_and_preserve_item_fallback(
    owner_principal,
    auth_user,
) -> None:
    async with AsyncSessionLocal() as session:
        restaurant = Restaurant(
            name="Analytics test", organization_id=auth_user["organization_id"]
        )
        session.add(restaurant)
        await session.flush()

        completed = Order(
            restaurant_id=restaurant.id,
            status="COMPLETED",
            subtotal=Decimal("12.00"),
            total=Decimal("12.00"),
            created_at=datetime(2026, 9, 16, 12, 0),
            updated_at=datetime(2026, 9, 16, 12, 0),
        )
        draft = Order(
            restaurant_id=restaurant.id,
            status="DRAFT",
            subtotal=Decimal("99.00"),
            total=Decimal("99.00"),
            created_at=datetime(2026, 9, 16, 13, 0),
            updated_at=datetime(2026, 9, 16, 13, 0),
        )
        session.add_all([completed, draft])
        await session.flush()
        session.add(
            OrderItem(
                order_id=completed.order_id,
                menu_item_id=None,
                quantity=2,
                unit_price=Decimal("6.00"),
                item_name="Historic item",
                line_total=Decimal("12.00"),
            )
        )
        await session.commit()

        service = AnalyticsService(session, owner_principal)
        dashboard = await service.get_restaurant_dashboard_analytics(
            restaurant.id,
            today=datetime(2026, 9, 16).date(),
        )

        assert dashboard.sales.value == Decimal("12.00")
        assert dashboard.orders.value == 1
        assert dashboard.top_selling_items[0].menu_item_id == 0
        assert dashboard.top_selling_items[0].quantity_sold == 2
        assert dashboard.sales_graph[-1].sales == Decimal("12.00")
