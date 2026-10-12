"""Fixed event routing; payload and Redis metadata cannot alter this registry."""

from collections.abc import Mapping
from types import MappingProxyType

from app.modules.events.domain.contracts import ConsumerName, EventType


_SUBSCRIPTIONS: dict[EventType, tuple[ConsumerName, ...]] = {
    "order.submitted.v1": ("notification_sink",),
    "order.accepted.v1": ("notification_sink",),
    "order.completed.v1": ("analytics", "notification_sink"),
    "order.cancelled.v1": ("notification_sink",),
    "order.deleted.v1": ("analytics", "notification_sink"),
    "menu.updated.v1": ("notification_sink",),
    "inventory.state_changed.v1": ("alerts",),
    "inventory.low.v1": ("alerts", "notification_sink"),
}
SUBSCRIPTIONS: Mapping[EventType, tuple[ConsumerName, ...]] = MappingProxyType(
    _SUBSCRIPTIONS
)


def consumers_for(event_type: EventType) -> tuple[ConsumerName, ...]:
    """Return the immutable subscription set for an approved event type."""
    return SUBSCRIPTIONS[event_type]
