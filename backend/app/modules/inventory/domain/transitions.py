"""Producer facts for revisioned inventory and low-stock episode transitions."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID


EpisodeResolutionReason = Literal["stock_recovered", "threshold_changed", "archived"]


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
class InventoryTransition:
    """Immutable state snapshot produced while holding the restaurant lock."""

    restaurant_id: int
    ingredient_id: int
    state_revision: int
    ingredient_name: str
    unit: Literal["g", "ml", "piece"]
    quantity: Decimal
    reorder_threshold: Decimal
    is_active: bool
    episode_id: UUID | None = None
    episode_transition: InventoryEpisodeTransition | None = None

    def __post_init__(self) -> None:
        if self.restaurant_id <= 0 or self.ingredient_id <= 0:
            raise ValueError("inventory transition identities must be positive")
        if self.state_revision < 1:
            raise ValueError("inventory state revision must be positive")
        if self.episode_transition is not None and self.episode_id != (
            self.episode_transition.episode_id
        ):
            raise ValueError("episode transition ID must match the current episode ID")

    @property
    def is_low(self) -> bool:
        """Derive low state from the approved active/quantity threshold rule."""
        return self.is_active and self.quantity <= self.reorder_threshold
