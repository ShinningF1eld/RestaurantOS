"""Delivery execution and operator queries; callers own all transactions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.repo.models import (
    EventDelivery,
    EventDeliveryAttempt,
    EventDeliveryReplay,
    EventReceipt,
    OutboxEvent,
)


def event_facts(event: OutboxEvent) -> dict[str, object]:
    return {
        key: getattr(event, key)
        for key in (
            "event_id",
            "event_type",
            "schema_version",
            "organization_id",
            "restaurant_id",
            "aggregate_type",
            "aggregate_id",
            "aggregate_revision",
            "occurred_at",
            "correlation_id",
            "payload",
        )
    }


async def lock_delivery(
    session: AsyncSession, event_id: UUID, consumer: str, *, skip_locked: bool = False
) -> EventDelivery | None:
    return await session.scalar(
        select(EventDelivery)
        .where(
            EventDelivery.event_id == event_id, EventDelivery.consumer_name == consumer
        )
        .with_for_update(skip_locked=skip_locked)
    )


async def receipt(
    session: AsyncSession, event_id: UUID, consumer: str
) -> EventReceipt | None:
    return await session.get(EventReceipt, (consumer, event_id))


async def clock(session: AsyncSession) -> datetime:
    # Unlike now(), this advances even after waiting for a competing row lock.
    return await session.scalar(select(func.clock_timestamp()))  # type: ignore[return-value]


async def next_attempt_number(session: AsyncSession, delivery: EventDelivery) -> int:
    number = await session.scalar(
        select(func.coalesce(func.max(EventDeliveryAttempt.attempt_number), 0)).where(
            EventDeliveryAttempt.delivery_id == delivery.id,
            EventDeliveryAttempt.retry_cycle == delivery.retry_cycle,
        )
    )
    return int(number or 0) + 1


async def running_attempts(
    session: AsyncSession, delivery_id: UUID
) -> list[EventDeliveryAttempt]:
    return list(
        await session.scalars(
            select(EventDeliveryAttempt).where(
                EventDeliveryAttempt.delivery_id == delivery_id,
                EventDeliveryAttempt.status == "running",
            )
        )
    )


async def replay_identity(
    session: AsyncSession, delivery: EventDelivery
) -> UUID | None:
    return await session.scalar(
        select(EventDeliveryReplay.replay_id).where(
            EventDeliveryReplay.delivery_id == delivery.id,
            EventDeliveryReplay.to_cycle == delivery.retry_cycle,
        )
    )


async def operator_identity(session: AsyncSession) -> str:
    # session_user is the authenticated connection role, not a CLI actor label
    # or SET ROLE's current_user. PostgreSQL credentials are the trust boundary.
    return str(await session.scalar(select(func.session_user())))


async def status_rows(session: AsyncSession) -> list[dict[str, object]]:
    now = await clock(session)
    result = []
    for consumer in ("analytics", "alerts", "notification_sink"):
        pending, oldest, retries, failed, retained = (
            await session.execute(
                select(
                    func.count().filter(
                        EventDelivery.status.in_(("pending", "processing"))
                    ),
                    func.min(EventDelivery.created_at).filter(
                        EventDelivery.status.in_(("pending", "processing"))
                    ),
                    func.count().filter(
                        or_(
                            and_(
                                EventDelivery.status == "pending",
                                EventDelivery.attempt_count > 0,
                            ),
                            and_(
                                EventDelivery.status == "processing",
                                EventDelivery.attempt_count > 1,
                            ),
                        ),
                    ),
                    func.count().filter(EventDelivery.status == "failed"),
                    func.count(),
                ).where(EventDelivery.consumer_name == consumer)
            )
        ).one()
        attempts = await session.scalar(
            select(func.count())
            .select_from(EventDeliveryAttempt)
            .join(EventDelivery, EventDelivery.id == EventDeliveryAttempt.delivery_id)
            .where(EventDelivery.consumer_name == consumer)
        )
        receipts = await session.scalar(
            select(func.count())
            .select_from(EventReceipt)
            .where(EventReceipt.consumer_name == consumer)
        )
        result.append(
            {
                "consumer": consumer,
                "pending": pending,
                "oldest_age_seconds": max(0, (now - oldest).total_seconds())
                if oldest
                else None,
                "retries": retries,
                "failed": failed,
                "retained_deliveries": retained,
                "retained_attempts": attempts,
                "retained_receipts": receipts,
            }
        )
    return result


async def history(
    session: AsyncSession, delivery_id: UUID
) -> tuple[list[EventDeliveryAttempt], list[EventDeliveryReplay]]:
    attempts = list(
        await session.scalars(
            select(EventDeliveryAttempt)
            .where(EventDeliveryAttempt.delivery_id == delivery_id)
            .order_by(
                EventDeliveryAttempt.retry_cycle, EventDeliveryAttempt.attempt_number
            )
        )
    )
    replays = list(
        await session.scalars(
            select(EventDeliveryReplay)
            .where(EventDeliveryReplay.delivery_id == delivery_id)
            .order_by(EventDeliveryReplay.to_cycle)
        )
    )
    return attempts, replays
