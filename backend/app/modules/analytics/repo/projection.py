"""Projection persistence and scoped authoritative comparisons; never commits."""

from datetime import date
from decimal import Decimal
from uuid import UUID
from typing import Literal, cast

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.domain.projection import Contribution, creation_date

# Register the related catalog/inventory mappers through the shared registry;
# standalone CLI/worker processes do not import FastAPI's application module.
from app.db.models import Order, Restaurant
from app.modules.analytics.repo.models import DailySales, OrderContribution
from app.modules.events.repo.models import OutboxEvent
from app.modules.events.domain.contracts import OrderDeletedPayload


class ProjectionRepository:
    def __init__(
        self, session: AsyncSession, organization_id: UUID, restaurant_id: int
    ) -> None:
        self.session = session
        self.organization_id = organization_id
        self.restaurant_id = restaurant_id

    async def scope(self, *, lock: bool = False) -> None:
        query = select(Restaurant.id).where(
            Restaurant.id == self.restaurant_id,
            Restaurant.organization_id == self.organization_id,
        )
        if lock:
            query = query.with_for_update()
        if await self.session.scalar(query) is None:
            raise ValueError("Unknown analytics scope")

    async def contributions(self) -> list[OrderContribution]:
        return list(
            await self.session.scalars(
                select(OrderContribution)
                .where(
                    OrderContribution.restaurant_id == self.restaurant_id,
                    OrderContribution.organization_id == self.organization_id,
                )
                .order_by(OrderContribution.order_id)
            )
        )

    @staticmethod
    def value(row: OrderContribution) -> Contribution:
        # Database constraints restrict state; constructing the domain value here
        # keeps persistence details out of the projection rules.
        return Contribution(
            row.order_id,
            row.revision,
            row.creation_date,
            row.total,
            cast(Literal["completed", "inactive", "deleted"], row.state),
        )

    async def get(self, order_id: int) -> OrderContribution | None:
        return await self.session.scalar(
            select(OrderContribution).where(
                OrderContribution.restaurant_id == self.restaurant_id,
                OrderContribution.organization_id == self.organization_id,
                OrderContribution.order_id == order_id,
            )
        )

    async def store(
        self, incoming: Contribution, row: OrderContribution | None
    ) -> None:
        if row is None:
            row = OrderContribution(
                restaurant_id=self.restaurant_id,
                organization_id=self.organization_id,
                order_id=incoming.order_id,
            )
            self.session.add(row)
        row.revision, row.creation_date, row.total, row.state = (
            incoming.revision,
            incoming.creation_date,
            incoming.total,
            incoming.state,
        )

    async def delta(self, day: date, count: int, sales: Decimal) -> None:
        row = await self.session.get(DailySales, (self.restaurant_id, day))
        if row is None:
            row = DailySales(
                restaurant_id=self.restaurant_id,
                organization_id=self.organization_id,
                creation_date=day,
                order_count=0,
                sales=Decimal("0.00"),
            )
            self.session.add(row)
        row.order_count += count
        row.sales += sales

    async def daily(self) -> dict[date, tuple[int, Decimal]]:
        rows = await self.session.scalars(
            select(DailySales)
            .where(
                DailySales.restaurant_id == self.restaurant_id,
                DailySales.organization_id == self.organization_id,
            )
            .order_by(DailySales.creation_date)
        )
        return {row.creation_date: (row.order_count, row.sales) for row in rows}

    async def authoritative(self) -> dict[date, tuple[int, Decimal]]:
        day = func.date(Order.created_at)
        rows = await self.session.execute(
            select(day, func.count(), func.sum(Order.total))
            .join(Restaurant)
            .where(
                Restaurant.id == self.restaurant_id,
                Restaurant.organization_id == self.organization_id,
                Order.status == "COMPLETED",
            )
            .group_by(day)
        )
        return {row[0]: (int(row[1]), Decimal(row[2])) for row in rows}

    async def baseline(self) -> dict[int, Contribution]:
        rows = await self.session.scalars(
            select(Order)
            .join(Restaurant)
            .where(
                Restaurant.id == self.restaurant_id,
                Restaurant.organization_id == self.organization_id,
            )
        )
        values = {
            row.order_id: Contribution(
                row.order_id,
                row.revision,
                creation_date(row.created_at),
                row.total if row.status == "COMPLETED" else Decimal("0.00"),
                "completed" if row.status == "COMPLETED" else "inactive",
            )
            for row in rows
        }
        # Deleted orders have no live row. Retained producer facts provide their
        # watermark even if their delivery has not yet run.
        events = await self.session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.restaurant_id == self.restaurant_id,
                OutboxEvent.organization_id == self.organization_id,
                OutboxEvent.event_type == "order.deleted.v1",
            )
        )
        for row in events:
            payload = OrderDeletedPayload.model_validate(row.payload)
            old = values.get(payload.order_id)
            if old is None or row.aggregate_revision > old.revision:
                values[payload.order_id] = Contribution(
                    payload.order_id,
                    row.aggregate_revision,
                    creation_date(payload.created_at),
                    Decimal("0.00"),
                    "deleted",
                )
        return values

    async def clear_daily(self) -> None:
        await self.session.execute(
            delete(DailySales).where(
                DailySales.restaurant_id == self.restaurant_id,
                DailySales.organization_id == self.organization_id,
            )
        )
