"""Allowlisted inventory alert HTTP responses."""

from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ActiveAlert(BaseModel):
    episode_id: UUID
    ingredient_id: int
    ingredient_name: str
    unit: Literal["g", "ml", "piece"]
    quantity: Decimal
    reorder_threshold: Decimal
    opened_at: datetime
    notification_suppressed: bool


class AlertHistory(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    episode_id: UUID
    ingredient_id: int
    ingredient_name: str
    unit: Literal["g", "ml", "piece"]
    opening_quantity: Decimal
    opening_threshold: Decimal
    opened_at: datetime
    opening_source: str
    notification_suppressed: bool
    resolved_at: datetime | None
    resolution_reason: (
        Literal["stock_recovered", "threshold_changed", "archived"] | None
    )


Item = TypeVar("Item")


class AlertPage(BaseModel, Generic[Item]):
    items: list[Item]
    total: int
    limit: int
    offset: int
