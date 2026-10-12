"""PostgreSQL outbox atomicity, scope, uniqueness, and retention behavior."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import AsyncSessionLocal
from app.db.models import Restaurant
from app.modules.events.domain.contracts import (
    OrderCompletedEvent,
    OrderCompletedPayload,
)
from app.modules.events.repo.models import EventDelivery, EventReceipt, OutboxEvent
from app.modules.events.service import (
    EventScopeMismatch,
    EventTransactionRequired,
    append_event,
)
from app.modules.orders.repo.models import Order
from app.modules.tenancy.repo.models import Organization
from conftest import engine


def create_restaurants() -> tuple[Organization, Restaurant, Organization, Restaurant]:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        organization_a = Organization(name="Events A", slug=f"events-a-{uuid4().hex}")
        organization_b = Organization(name="Events B", slug=f"events-b-{uuid4().hex}")
        db.add_all([organization_a, organization_b])
        db.flush()
        restaurant_a = Restaurant(name="Branch A", organization_id=organization_a.id)
        restaurant_b = Restaurant(name="Branch B", organization_id=organization_b.id)
        db.add_all([restaurant_a, restaurant_b])
        db.flush()
    return organization_a, restaurant_a, organization_b, restaurant_b


def completed_envelope(organization_id, restaurant_id, *, order_id: int = 17):
    return OrderCompletedEvent(
        organization_id=organization_id,
        restaurant_id=restaurant_id,
        aggregate_id=str(order_id),
        aggregate_revision=2,
        occurred_at=datetime.now(UTC),
        correlation_id="integration-correlation",
        payload=OrderCompletedPayload(
            order_id=order_id,
            total=Decimal("50.00"),
            created_at=datetime(2026, 10, 11, 5, 30),
        ),
    )


def append_in_transaction(envelope):
    async def run():
        async with AsyncSessionLocal() as db, db.begin():
            return await append_event(db, envelope)

    return asyncio.run(run())


def test_append_fans_out_and_survives_business_entity_deletion() -> None:
    organization, restaurant, _, _ = create_restaurants()
    with Session(engine, expire_on_commit=False) as db, db.begin():
        order = Order(
            restaurant_id=restaurant.id,
            status="COMPLETED",
            payment_status="UNPAID",
            subtotal=Decimal("50.00"),
            total=Decimal("50.00"),
        )
        db.add(order)
        db.flush()
        order_id = order.order_id

    event_id = append_in_transaction(
        completed_envelope(organization.id, restaurant.id, order_id=order_id)
    ).event_id
    with Session(engine, expire_on_commit=False) as db, db.begin():
        db.execute(delete(Order).where(Order.order_id == order_id))

    with Session(engine) as db:
        saved = db.get(OutboxEvent, event_id)
        assert saved is not None
        deliveries = db.scalars(
            select(EventDelivery)
            .where(EventDelivery.event_id == event_id)
            .order_by(EventDelivery.consumer_name)
        ).all()
        assert [delivery.consumer_name for delivery in deliveries] == [
            "analytics",
            "notification_sink",
        ]

    with pytest.raises(IntegrityError, match="outbox event facts are immutable"):
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM outbox_events WHERE event_id=:event_id"),
                {"event_id": event_id},
            )


def test_append_rolls_back_event_and_all_deliveries_with_caller_transaction() -> None:
    organization, restaurant, _, _ = create_restaurants()
    envelope = completed_envelope(organization.id, restaurant.id)

    async def run() -> None:
        async with AsyncSessionLocal() as db:
            with pytest.raises(RuntimeError, match="simulated business failure"):
                async with db.begin():
                    await append_event(db, envelope)
                    raise RuntimeError("simulated business failure")

    asyncio.run(run())
    with Session(engine) as db:
        assert db.get(OutboxEvent, envelope.event_id) is None
        assert (
            db.scalars(
                select(EventDelivery).where(EventDelivery.event_id == envelope.event_id)
            ).all()
            == []
        )


def test_subscription_fanout_constraint_failure_rolls_back_every_row() -> None:
    organization, restaurant, _, _ = create_restaurants()
    envelope = completed_envelope(organization.id, restaurant.id)

    async def run() -> None:
        async with AsyncSessionLocal() as db:
            with pytest.raises(IntegrityError):
                async with db.begin():
                    await append_event(db, envelope)
                    db.add(
                        EventDelivery(
                            event_id=envelope.event_id,
                            consumer_name="analytics",
                        )
                    )

    asyncio.run(run())
    with Session(engine) as db:
        assert db.get(OutboxEvent, envelope.event_id) is None
        assert (
            db.scalars(
                select(EventDelivery).where(EventDelivery.event_id == envelope.event_id)
            ).all()
            == []
        )


def test_append_rejects_wrong_scope_and_transactionless_call() -> None:
    organization_a, _, _, restaurant_b = create_restaurants()
    wrong_scope = completed_envelope(organization_a.id, restaurant_b.id)

    async def run() -> None:
        async with AsyncSessionLocal() as db:
            with pytest.raises(EventTransactionRequired):
                await append_event(db, wrong_scope)
            with pytest.raises(EventScopeMismatch):
                async with db.begin():
                    await append_event(db, wrong_scope)

    asyncio.run(run())
    with Session(engine) as db:
        assert db.get(OutboxEvent, wrong_scope.event_id) is None


def test_receipt_is_unique_per_consumer_and_event() -> None:
    organization, restaurant, _, _ = create_restaurants()
    event_id = append_in_transaction(
        completed_envelope(organization.id, restaurant.id)
    ).event_id
    with Session(engine) as db, db.begin():
        db.add(
            EventReceipt(
                consumer_name="analytics", event_id=event_id, outcome="processed"
            )
        )
    with pytest.raises(IntegrityError):
        with Session(engine) as db, db.begin():
            db.add(
                EventReceipt(
                    consumer_name="analytics", event_id=event_id, outcome="processed"
                )
            )
