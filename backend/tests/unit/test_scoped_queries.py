"""Compile the actual repository predicates without connecting to PostgreSQL."""

from uuid import uuid4
from datetime import datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.tenancy.domain.policies import AccessContext
from app.modules.tenancy.domain.roles import MembershipRole
from app.modules.restaurants.repo.queries import RestaurantRepository
from app.modules.catalog.repo.queries import CatalogRepository
from app.modules.orders.repo.queries import OrderRepository
from app.modules.analytics.repo.queries import AnalyticsRepository


class Result:
    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self

    def all(self):
        return []

    def one(self):
        return (0, 0)


class CaptureSession:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return Result()

    async def scalar(self, statement):
        self.statements.append(statement)
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(MembershipRole))
async def test_business_read_queries_filter_organization_and_assigned_restaurants(role):
    session = CaptureSession()
    context = AccessContext(uuid4(), uuid4(), uuid4(), 1, role, frozenset({7, 8}))
    restaurants = RestaurantRepository(session, context)
    catalog = CatalogRepository(session, context)
    orders = OrderRepository(session, context)
    analytics = AnalyticsRepository(session, context)
    await restaurants.get_by_id(7)
    await restaurants.list_all()
    await catalog.get_menu_by_id(11)
    await catalog.get_menu_item_by_id(12)
    await catalog.list_menus_for_restaurant(7)
    await catalog.list_menu_items_for_menu(11)
    await catalog.menu_item_has_order_history(12)
    await orders.get_by_id(13, lock=True)
    await orders.list_for_restaurant(7, 25, 0)
    await orders.count_for_restaurant(7)
    await orders.menu_items_for_restaurant(7, [12])
    await analytics.restaurant_exists(7)
    await analytics.get_completed_totals(7, datetime(2026, 1, 1), datetime(2026, 1, 2))
    await analytics.get_sales_graph(7, datetime(2026, 1, 1), datetime(2026, 1, 2))
    await analytics.get_top_selling_items(7, datetime(2026, 1, 1), datetime(2026, 1, 2))
    for statement in session.statements:
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert f"restaurants.organization_id = '{context.organization_id}'" in sql
        assert (
            "restaurants.id IN (7, 8)" in sql or "restaurants.id IN (8, 7)" in sql
        ) == (role is not MembershipRole.OWNER)
    assert "FOR UPDATE OF orders" in str(
        session.statements[7].compile(dialect=postgresql.dialect())
    )
