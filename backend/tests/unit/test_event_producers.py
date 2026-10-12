"""Producer correlation and legacy inventory contracts without persistence."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.request_id import reset_request_id, set_request_id
from app.modules.events.domain.contracts import InventoryStateChangedPayload
from app.modules.events.service import CommandEvents


def test_command_correlation_reuses_request_and_generates_per_command_fallback():
    first, second = CommandEvents(), CommandEvents()
    assert first.correlation_id != second.correlation_id
    token = set_request_id("command-request")
    try:
        assert CommandEvents().correlation_id == "command-request"
    finally:
        reset_request_id(token)


def test_legacy_low_snapshot_is_valid_but_opening_requires_episode_identity():
    state = InventoryStateChangedPayload(
        ingredient_id=1,
        ingredient_name="Rice",
        unit="g",
        quantity="2",
        reorder_threshold="5",
        is_active=True,
        is_low=True,
    )
    assert state.episode_id is None
    with pytest.raises(ValidationError):
        InventoryStateChangedPayload(
            **{**state.model_dump(), "episode_transition": "opened"}
        )


@pytest.mark.asyncio
async def test_same_direct_command_appends_distinct_events_with_shared_correlation(
    monkeypatch,
):
    import app.modules.events.service as module

    captured = []

    async def append(session, envelope):
        captured.append(envelope)

    monkeypatch.setattr(module, "append_event", append)
    command = CommandEvents()
    for status in ("order.submitted.v1", "order.accepted.v1"):
        await command.append(
            object(),
            event_type=status,
            organization_id=uuid4(),
            restaurant_id=1,
            aggregate_type="order",
            aggregate_id=1,
            aggregate_revision=2,
            payload={"order_id": 1},
        )
    assert captured[0].event_id != captured[1].event_id
    assert (
        captured[0].correlation_id
        == captured[1].correlation_id
        == command.correlation_id
    )
    assert captured[0].occurred_at == captured[1].occurred_at
