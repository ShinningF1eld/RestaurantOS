from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.inventory.domain.transitions import (
    InventoryEpisodeFacts,
    InventoryEpisodeTransition,
    InventoryStateSnapshot,
    InventoryTransition,
    episode_resolution_reason,
    inventory_state_changed,
    low_episode_transition,
)


def state(
    *,
    name: str = "Rice",
    unit: str = "g",
    quantity: str = "5",
    threshold: str = "5",
    active: bool = True,
    revision: int = 1,
) -> InventoryStateSnapshot:
    return InventoryStateSnapshot(
        organization_id=uuid4(),
        restaurant_id=1,
        ingredient_id=2,
        state_revision=revision,
        ingredient_name=name,
        unit=unit,  # type: ignore[arg-type]
        quantity=Decimal(quantity),
        reorder_threshold=Decimal(threshold),
        is_active=active,
    )


@pytest.mark.parametrize(
    "quantity,threshold,active,expected",
    [
        ("0", "0", True, True),
        ("5", "5", True, True),
        ("5.001", "5", True, False),
        ("0", "5", False, False),
    ],
)
def test_low_predicate_includes_zero_at_zero_threshold(
    quantity, threshold, active, expected
) -> None:
    assert (
        state(quantity=quantity, threshold=threshold, active=active).is_low is expected
    )


def test_only_balance_threshold_and_active_changes_advance_state_revision() -> None:
    original = state()
    assert inventory_state_changed(None, original)
    assert not inventory_state_changed(
        original, state(name="Renamed", unit="ml", revision=1)
    )
    assert inventory_state_changed(original, state(quantity="4", revision=1))
    assert inventory_state_changed(original, state(threshold="4", revision=1))
    assert inventory_state_changed(original, state(active=False, revision=1))


@pytest.mark.parametrize(
    "before,after,reason",
    [
        (
            state(quantity="0", threshold="0"),
            state(quantity="0", active=False),
            "archived",
        ),
        (
            state(quantity="5", threshold="5"),
            state(quantity="5", threshold="4", revision=1),
            "threshold_changed",
        ),
        (
            state(quantity="5", threshold="5"),
            state(quantity="6", threshold="5", revision=1),
            "stock_recovered",
        ),
    ],
)
def test_resolution_reason_uses_the_state_change_that_closed_low(
    before, after, reason
) -> None:
    assert episode_resolution_reason(before, after) == reason


def test_archiving_takes_precedence_when_threshold_changes_too() -> None:
    before = state(quantity="0", threshold="5")
    after = state(quantity="0", threshold="0", active=False, revision=2)
    assert episode_resolution_reason(before, after) == "archived"


def test_episode_boundaries_cover_creation_recovery_and_normal_restoration() -> None:
    low = state(quantity="0", threshold="0")
    assert low_episode_transition(None, low) == "opened"
    assert low_episode_transition(state(quantity="1", threshold="0"), low) == "opened"
    assert low_episode_transition(low, state(quantity="0", threshold="0")) is None

    archived_normal = state(quantity="10", threshold="5", active=False)
    restored_normal = state(quantity="10", threshold="5", active=True)
    assert low_episode_transition(archived_normal, restored_normal) is None
    assert low_episode_transition(low, state(quantity="1", threshold="0")) == "resolved"


def test_episode_facts_require_complete_timezone_aware_resolution() -> None:
    now = datetime.now(UTC)
    base = {
        "episode_id": uuid4(),
        "organization_id": uuid4(),
        "restaurant_id": 1,
        "ingredient_id": 2,
        "ingredient_name": "Rice",
        "unit": "g",
        "opening_quantity": Decimal("5"),
        "opening_reorder_threshold": Decimal("5"),
        "opened_at": now,
        "opening_revision": 1,
        "opening_source": "stock_command",
        "opening_actor_user_id": None,
        "opening_order_id": None,
        "notification_suppressed": False,
    }
    facts = InventoryEpisodeFacts(**base)
    assert facts.resolved_at is None

    with pytest.raises(ValueError, match="resolution facts must be complete"):
        InventoryEpisodeFacts(
            **base,
            resolved_at=now,
            resolution_reason="stock_recovered",
        )


def test_open_episode_transition_cannot_claim_a_resolution_reason() -> None:
    with pytest.raises(ValueError, match="opened episode"):
        InventoryEpisodeTransition(
            episode_id=uuid4(),
            kind="opened",
            occurred_at=datetime.now(UTC),
            resolution_reason="stock_recovered",
        )


@pytest.mark.parametrize(
    "quantity,active,kind,reason",
    [
        ("6", True, "opened", None),
        ("2", False, "opened", None),
        ("2", True, "resolved", "stock_recovered"),
    ],
)
def test_producer_transition_rejects_contradictory_episode_state(
    quantity, active, kind, reason
) -> None:
    episode_id = uuid4()
    snapshot = state(quantity=quantity, active=active)
    with pytest.raises(ValueError, match="resulting state"):
        InventoryTransition(
            organization_id=snapshot.organization_id,
            restaurant_id=snapshot.restaurant_id,
            ingredient_id=snapshot.ingredient_id,
            state_revision=snapshot.state_revision,
            ingredient_name=snapshot.ingredient_name,
            unit=snapshot.unit,
            quantity=snapshot.quantity,
            reorder_threshold=snapshot.reorder_threshold,
            is_active=snapshot.is_active,
            episode_id=episode_id,
            episode_transition=InventoryEpisodeTransition(
                episode_id=episode_id,
                kind=kind,
                occurred_at=datetime.now(UTC),
                resolution_reason=reason,
            ),
        )


def test_legacy_low_producer_snapshot_can_wait_for_episode_initialization() -> None:
    snapshot = state(quantity="0", threshold="0")
    transition = InventoryTransition(
        organization_id=snapshot.organization_id,
        restaurant_id=snapshot.restaurant_id,
        ingredient_id=snapshot.ingredient_id,
        state_revision=snapshot.state_revision,
        ingredient_name=snapshot.ingredient_name,
        unit=snapshot.unit,
        quantity=snapshot.quantity,
        reorder_threshold=snapshot.reorder_threshold,
        is_active=snapshot.is_active,
    )
    assert transition.is_low
    assert transition.episode_id is None
    assert transition.episode_transition is None
