"""Pure state and episode facts for revisioned inventory transitions."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID


EpisodeResolutionReason = Literal["stock_recovered", "threshold_changed", "archived"]
InventoryTransitionSource = Literal[
    "ingredient_creation",
    "ingredient_update",
    "stock_command",
    "order_acceptance",
    "maintenance_initialization",
]
InventoryUnit = Literal["g", "ml", "piece"]


@dataclass(frozen=True, slots=True)
class InventoryStateSnapshot:
    """Relevant authoritative state captured before a write, under the restaurant lock."""

    organization_id: UUID
    restaurant_id: int
    ingredient_id: int
    state_revision: int
    ingredient_name: str
    unit: InventoryUnit
    quantity: Decimal
    reorder_threshold: Decimal
    is_active: bool

    @property
    def is_low(self) -> bool:
        return self.is_active and self.quantity <= self.reorder_threshold


@dataclass(frozen=True, slots=True)
class InventoryEpisodeTransition:
    episode_id: UUID
    kind: Literal["opened", "resolved"]
    occurred_at: datetime
    resolution_reason: EpisodeResolutionReason | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("inventory episode transition time must be timezone-aware")
        if self.kind == "opened" and self.resolution_reason is not None:
            raise ValueError("an opened episode cannot have a resolution reason")
        if self.kind == "resolved" and self.resolution_reason is None:
            raise ValueError("a resolved episode requires a resolution reason")


@dataclass(frozen=True, slots=True)
class InventoryEpisodeFacts:
    """Immutable opening facts plus the optional committed resolution facts."""

    episode_id: UUID
    organization_id: UUID
    restaurant_id: int
    ingredient_id: int
    ingredient_name: str
    unit: InventoryUnit
    opening_quantity: Decimal
    opening_reorder_threshold: Decimal
    opened_at: datetime
    opening_revision: int
    opening_source: InventoryTransitionSource
    opening_actor_user_id: UUID | None
    opening_order_id: int | None
    notification_suppressed: bool
    resolved_at: datetime | None = None
    resolution_reason: EpisodeResolutionReason | None = None
    closing_quantity: Decimal | None = None
    closing_reorder_threshold: Decimal | None = None
    closing_is_active: bool | None = None
    resolution_revision: int | None = None
    resolution_source: InventoryTransitionSource | None = None
    resolution_actor_user_id: UUID | None = None
    resolution_order_id: int | None = None

    def __post_init__(self) -> None:
        if self.restaurant_id <= 0 or self.ingredient_id <= 0:
            raise ValueError("inventory episode identities must be positive")
        if self.opening_revision < 1:
            raise ValueError("inventory episode opening revision must be positive")
        if self.opened_at.tzinfo is None or self.opened_at.utcoffset() is None:
            raise ValueError("inventory episode opening time must be timezone-aware")
        resolution_values = (
            self.resolved_at,
            self.resolution_reason,
            self.closing_quantity,
            self.closing_reorder_threshold,
            self.closing_is_active,
            self.resolution_revision,
            self.resolution_source,
        )
        if any(value is not None for value in resolution_values) and not all(
            value is not None for value in resolution_values
        ):
            raise ValueError("inventory episode resolution facts must be complete")
        if self.resolved_at is not None and (
            self.resolved_at.tzinfo is None or self.resolved_at.utcoffset() is None
        ):
            raise ValueError("inventory episode resolution time must be timezone-aware")
        if self.resolution_revision is not None and (
            self.resolution_revision <= self.opening_revision
        ):
            raise ValueError("resolution revision must follow the opening revision")
        if self.notification_suppressed and (
            self.opening_source != "maintenance_initialization"
        ):
            raise ValueError("only initialization baseline episodes suppress notices")


@dataclass(frozen=True, slots=True)
class InventoryTransition:
    """Immutable resulting state and episode facts produced by inventory writes."""

    organization_id: UUID
    restaurant_id: int
    ingredient_id: int
    state_revision: int
    ingredient_name: str
    unit: InventoryUnit
    quantity: Decimal
    reorder_threshold: Decimal
    is_active: bool
    episode_id: UUID | None = None
    episode_transition: InventoryEpisodeTransition | None = None
    episode_facts: InventoryEpisodeFacts | None = None

    def __post_init__(self) -> None:
        if self.restaurant_id <= 0 or self.ingredient_id <= 0:
            raise ValueError("inventory transition identities must be positive")
        if self.state_revision < 1:
            raise ValueError("inventory state revision must be positive")
        if self.episode_transition is not None and self.episode_id != (
            self.episode_transition.episode_id
        ):
            raise ValueError("episode transition ID must match the current episode ID")
        if self.episode_facts is not None and self.episode_id != (
            self.episode_facts.episode_id
        ):
            raise ValueError("episode facts ID must match the current episode ID")

    @property
    def is_low(self) -> bool:
        """Derive low state from the approved active/quantity threshold rule."""
        return self.is_active and self.quantity <= self.reorder_threshold


def inventory_state_changed(
    before: InventoryStateSnapshot | None, after: InventoryStateSnapshot
) -> bool:
    """Return whether balance, threshold, or active state genuinely changed."""
    if before is None:
        return True
    return (
        before.quantity != after.quantity
        or before.reorder_threshold != after.reorder_threshold
        or before.is_active != after.is_active
    )


def low_episode_transition(
    before: InventoryStateSnapshot | None, after: InventoryStateSnapshot
) -> Literal["opened", "resolved"] | None:
    """Return a boundary only when the authoritative low predicate changes."""
    was_low = before.is_low if before is not None else False
    if not was_low and after.is_low:
        return "opened"
    if was_low and not after.is_low:
        return "resolved"
    return None


def episode_resolution_reason(
    before: InventoryStateSnapshot, after: InventoryStateSnapshot
) -> EpisodeResolutionReason:
    """Choose the approved reason for a low-to-normal/inactive transition."""
    if not before.is_low or after.is_low:
        raise ValueError("resolution reasons apply only when a low episode closes")
    if before.is_active and not after.is_active:
        return "archived"
    if before.reorder_threshold != after.reorder_threshold:
        return "threshold_changed"
    return "stock_recovered"
