"""Pure event contract, serialization, and revision tests."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.events.domain.contracts import (
    InventoryLowPayload,
    InventoryStateChangedEvent,
    InventoryStateChangedPayload,
    OrderCompletedEvent,
    OrderCompletedPayload,
    UnsupportedEventVersion,
    deserialize_event,
    serialize_event,
)
from app.modules.events.domain.subscriptions import SUBSCRIPTIONS, consumers_for
from app.modules.inventory.domain.transitions import (
    InventoryEpisodeTransition,
    InventoryTransition,
)
from app.modules.orders.domain.revisions import next_order_revision


def completed_event(*, created_at: datetime | None = None) -> OrderCompletedEvent:
    return OrderCompletedEvent(
        organization_id=uuid4(),
        restaurant_id=1,
        aggregate_id="27",
        aggregate_revision=3,
        occurred_at=datetime(2026, 10, 11, 6, 0, tzinfo=UTC),
        correlation_id="request-27",
        payload=OrderCompletedPayload(
            order_id=27,
            total=Decimal("99999999.99"),
            created_at=created_at or datetime(2026, 10, 11, 5, 30),
        ),
    )


def test_event_serialization_is_lossless_and_legacy_order_time_is_utc() -> None:
    event = completed_event()

    encoded = serialize_event(event)
    restored = deserialize_event(event.model_dump_json())

    assert encoded["payload"]["total"] == "99999999.99"
    assert event.payload.created_at == datetime(2026, 10, 11, 5, 30, tzinfo=UTC)
    assert restored.event_id == event.event_id
    assert isinstance(restored, OrderCompletedEvent)
    assert restored.payload.total == Decimal("99999999.99")
    assert restored.payload.created_at.date() == event.payload.created_at.date()


@pytest.mark.parametrize(
    ("event_type", "schema_version"),
    [("order.completed.v2", 2), ("order.completed.v1", 2)],
)
def test_deserialization_rejects_unsupported_type_or_version(
    event_type: str, schema_version: int
) -> None:
    raw = serialize_event(completed_event())
    raw["event_type"] = event_type
    raw["schema_version"] = schema_version

    with pytest.raises(UnsupportedEventVersion):
        deserialize_event(raw)


def test_contract_rejects_unsafe_decimal_numeric_and_identity_mismatch() -> None:
    with pytest.raises(
        ValidationError, match="decimal values must be supplied as strings"
    ):
        OrderCompletedPayload.model_validate(
            {"order_id": 1, "total": 2.1, "created_at": "2026-10-11T00:00:00"}
        )
    with pytest.raises(ValidationError, match="at most two decimal places"):
        OrderCompletedPayload.model_validate(
            {"order_id": 1, "total": "1.001", "created_at": "2026-10-11T00:00:00"}
        )
    with pytest.raises(ValidationError, match="aggregate ID must match"):
        OrderCompletedEvent(
            organization_id=uuid4(),
            restaurant_id=1,
            aggregate_id="28",
            aggregate_revision=1,
            occurred_at=datetime.now(UTC),
            correlation_id="request-28",
            payload=OrderCompletedPayload(
                order_id=27,
                total=Decimal("1.00"),
                created_at=datetime.now(UTC),
            ),
        )


def test_fixed_subscription_matrix_contains_only_approved_consumers() -> None:
    assert set(SUBSCRIPTIONS) == {
        "order.submitted.v1",
        "order.accepted.v1",
        "order.completed.v1",
        "order.cancelled.v1",
        "order.deleted.v1",
        "menu.updated.v1",
        "inventory.state_changed.v1",
        "inventory.low.v1",
    }
    assert consumers_for("order.completed.v1") == ("analytics", "notification_sink")
    assert consumers_for("inventory.low.v1") == ("alerts", "notification_sink")
    assert all(
        consumer in {"analytics", "alerts", "notification_sink"}
        for consumers in SUBSCRIPTIONS.values()
        for consumer in consumers
    )


def test_order_revision_helper_and_inventory_transition_contract() -> None:
    assert next_order_revision(1) == 2
    with pytest.raises(ValueError):
        next_order_revision(0)

    episode_id = uuid4()
    transition = InventoryTransition(
        organization_id=uuid4(),
        restaurant_id=1,
        ingredient_id=8,
        state_revision=4,
        ingredient_name="Rice",
        unit="g",
        quantity=Decimal("2.500"),
        reorder_threshold=Decimal("5.000"),
        is_active=True,
        episode_id=episode_id,
        episode_transition=InventoryEpisodeTransition(
            episode_id=episode_id,
            kind="opened",
            occurred_at=datetime.now(UTC),
        ),
    )
    assert transition.state_revision == 4
    assert transition.is_low is True


@pytest.mark.parametrize(
    "quantity,active,is_low,transition,reason",
    [
        ("10.000", True, False, "opened", None),
        ("2.000", False, False, "opened", None),
        ("2.000", True, True, "resolved", "stock_recovered"),
    ],
)
def test_inventory_event_rejects_contradictory_episode_state(
    quantity, active, is_low, transition, reason
) -> None:
    payload = {
        "ingredient_id": 8,
        "ingredient_name": "Rice",
        "unit": "g",
        "quantity": quantity,
        "reorder_threshold": "5.000",
        "is_active": active,
        "is_low": is_low,
        "episode_id": str(uuid4()),
        "episode_transition": transition,
        "resolution_reason": reason,
    }
    with pytest.raises(ValidationError, match="resulting state"):
        InventoryStateChangedPayload.model_validate(payload)
    raw = {
        "event_type": "inventory.state_changed.v1",
        "schema_version": 1,
        "organization_id": str(uuid4()),
        "restaurant_id": 1,
        "aggregate_type": "ingredient",
        "aggregate_id": "8",
        "aggregate_revision": 4,
        "occurred_at": "2026-10-11T06:00:00Z",
        "correlation_id": "inventory-review",
        "payload": payload,
    }
    with pytest.raises(ValueError, match="contract validation"):
        deserialize_event(raw)


@pytest.mark.parametrize(
    "quantity,threshold,active,transition,reason",
    [
        ("0.000", "0.000", True, "opened", None),
        ("5.000", "5.000", True, "opened", None),
        ("2.000", "5.000", True, None, None),
        ("6.000", "5.000", True, "resolved", "stock_recovered"),
        ("5.000", "4.000", True, "resolved", "threshold_changed"),
        ("2.000", "5.000", False, "resolved", "archived"),
    ],
)
def test_inventory_event_preserves_valid_episode_boundaries(
    quantity, threshold, active, transition, reason
) -> None:
    payload = InventoryStateChangedPayload(
        ingredient_id=8,
        ingredient_name="Rice",
        unit="g",
        quantity=quantity,
        reorder_threshold=threshold,
        is_active=active,
        is_low=active and Decimal(quantity) <= Decimal(threshold),
        episode_id=uuid4(),
        episode_transition=transition,
        resolution_reason=reason,
    )
    event = InventoryStateChangedEvent(
        organization_id=uuid4(),
        restaurant_id=1,
        aggregate_id="8",
        aggregate_revision=4,
        occurred_at=datetime.now(UTC),
        correlation_id="inventory-review",
        payload=payload,
    )
    assert deserialize_event(serialize_event(event)) == event


@pytest.mark.parametrize("quantity,threshold", [("0.000", "0.000"), ("5.000", "5.000")])
def test_low_episode_accepts_quantity_at_threshold(quantity, threshold) -> None:
    payload = InventoryLowPayload(
        ingredient_id=8,
        episode_id=uuid4(),
        ingredient_name="Rice",
        unit="g",
        opening_quantity=quantity,
        reorder_threshold=threshold,
        opened_at=datetime.now(UTC),
    )
    assert payload.opening_quantity == Decimal(quantity)


def test_low_episode_rejects_opening_quantity_above_threshold() -> None:
    with pytest.raises(ValidationError, match="opening quantity"):
        InventoryLowPayload(
            ingredient_id=8,
            episode_id=uuid4(),
            ingredient_name="Rice",
            unit="g",
            opening_quantity="5.001",
            reorder_threshold="5.000",
            opened_at=datetime.now(UTC),
        )
