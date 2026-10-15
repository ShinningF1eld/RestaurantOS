"""Application service for restaurant dashboard analytics."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from app.modules.analytics.domain.calculations import (
    start_of_day as start_of_day,
    end_of_day as end_of_day,
    percent_change as percent_change,
)

from app.core.errors import NotFoundError
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.tenancy.access import AccessService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.modules.analytics.repo.queries import AnalyticsRepository
from app.modules.analytics.repo.queries import (
    CompletedTotals,
    SalesGraphRow,
    TopSellingItemRow,
)


from app.modules.analytics.domain.values import (
    DashboardMetricData as DashboardMetricData,
    SalesPointData as SalesPointData,
    TopSellingItemData as TopSellingItemData,
    RestaurantDashboardAnalyticsData as RestaurantDashboardAnalyticsData,
)


from app.modules.analytics.domain.projection import (
    Contribution,
    creation_date,
    should_apply,
)
from app.modules.analytics.repo.projection import ProjectionRepository
from app.modules.events.domain.contracts import (
    EventEnvelope,
    OrderCompletedEvent,
    OrderDeletedEvent,
)


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


class AnalyticsService:
    """Coordinate dashboard queries and calculate presentation-ready values."""

    def __init__(
        self,
        session: AsyncSession,
        principal: AuthenticatedPrincipal,
        repository: AnalyticsRepositoryPort | None = None,
    ) -> None:
        self._session = session
        self._access = AccessService(session, principal)
        self._provided_repository = repository

    async def get_restaurant_dashboard_analytics(
        self,
        restaurant_id: int,
        *,
        today: date | None = None,
    ) -> RestaurantDashboardAnalyticsData:
        context = await self._access.current()
        await self._access.restaurant(context, restaurant_id, "analytics.read")
        self._repository = self._provided_repository or AnalyticsRepository(
            self._session, context
        )
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


async def apply_order_event(
    session: AsyncSession, event: EventEnvelope
) -> Literal["processed", "skipped"]:
    """Stage effects in the execution service's receipt transaction; no I/O/commit.

    The restaurant row serializes all analytics changes for a branch, including
    first inserts and different orders on the same day. Maintenance shares this
    lock. No network work occurs while holding it.
    """
    if not session.in_transaction():
        raise RuntimeError("Analytics effects require a caller transaction")
    if not isinstance(event, (OrderCompletedEvent, OrderDeletedEvent)):
        raise ValueError("Unsupported analytics event")
    repo = ProjectionRepository(session, event.organization_id, event.restaurant_id)
    await repo.scope(lock=True)
    incoming = Contribution(
        event.payload.order_id,
        event.aggregate_revision,
        creation_date(event.payload.created_at),
        event.payload.total
        if isinstance(event, OrderCompletedEvent)
        else Decimal("0.00"),
        "completed" if isinstance(event, OrderCompletedEvent) else "deleted",
    )
    row = await repo.get(incoming.order_id)
    current = repo.value(row) if row is not None else None
    if not should_apply(current, incoming):
        return "skipped"
    if current is not None and current.count:
        await repo.delta(current.creation_date, -1, -current.total)
    if incoming.count:
        await repo.delta(incoming.creation_date, 1, incoming.total)
    await repo.store(incoming, row)
    await session.flush()
    return "processed"


class AnalyticsProjectionService:
    """Database-credential operator access; no user-facing authorization bypass.

    Rebuild requires stopped workers and quiesced writes (T8 orchestrates this).
    A transaction and shared restaurant lock also fence already waiting effects.
    Receipts, deliveries and producer history are never reset or deleted.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def inspect(
        self, organization_id: UUID, restaurant_id: int
    ) -> dict[str, object]:
        async with self.sessions() as session, session.begin():
            repo = ProjectionRepository(session, organization_id, restaurant_id)
            await repo.scope(lock=True)
            return {
                "organization_id": str(organization_id),
                "restaurant_id": restaurant_id,
                "daily": [
                    {
                        "creation_date": str(day),
                        "order_count": count,
                        "sales": str(sales),
                    }
                    for day, (count, sales) in (await repo.daily()).items()
                ],
                "orders": [
                    {
                        "order_id": row.order_id,
                        "revision": row.revision,
                        "creation_date": str(row.creation_date),
                        "total": str(row.total),
                        "state": row.state,
                    }
                    for row in await repo.contributions()
                ],
            }

    async def reconcile(
        self, organization_id: UUID, restaurant_id: int
    ) -> dict[str, object]:
        async with self.sessions() as session, session.begin():
            repo = ProjectionRepository(session, organization_id, restaurant_id)
            await repo.scope(lock=True)
            projected, authoritative = await repo.daily(), await repo.authoritative()
            differences = []
            for day in sorted(projected.keys() | authoritative.keys()):
                actual = authoritative.get(day, (0, Decimal("0.00")))
                derived = projected.get(day, (0, Decimal("0.00")))
                if actual != derived:
                    differences.append(
                        {
                            "creation_date": str(day),
                            "authoritative_count": actual[0],
                            "authoritative_sales": str(actual[1]),
                            "projected_count": derived[0],
                            "projected_sales": str(derived[1]),
                        }
                    )
            return {
                "organization_id": str(organization_id),
                "restaurant_id": restaurant_id,
                "matches": not differences,
                "discrepancies": differences,
            }

    async def rebuild(self, organization_id: UUID, restaurant_id: int) -> None:
        """Maintenance-only seed/rebuild, repeatable with queued events retained."""
        async with self.sessions() as session, session.begin():
            await rebuild_analytics_projection(session, organization_id, restaurant_id)


async def rebuild_analytics_projection(
    session: AsyncSession, organization_id: UUID, restaurant_id: int
) -> None:
    """Public transaction-bound maintenance interface; preserve receipts and history."""
    if not session.in_transaction():
        raise RuntimeError("Analytics rebuild requires a caller transaction")
    repo = ProjectionRepository(session, organization_id, restaurant_id)
    await repo.scope(lock=True)
    baseline = await repo.baseline()
    existing = {row.order_id: row for row in await repo.contributions()}
    # Never forget existing deletion watermarks. An absent completed row
    # without a producer deletion fact is unsafe to silently discard.
    for order_id, row in existing.items():
        if order_id not in baseline:
            if row.state != "deleted":
                raise ValueError("Missing authoritative order/deletion fact")
            baseline[order_id] = repo.value(row)
    await repo.clear_daily()
    for value in baseline.values():
        await repo.store(value, existing.get(value.order_id))
        if value.count:
            await repo.delta(value.creation_date, 1, value.total)
    await session.flush()
