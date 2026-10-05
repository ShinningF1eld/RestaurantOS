from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CreateIngredient:
    name: str
    unit: str
    reorder_threshold: Decimal
    opening_quantity: Decimal
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class UpdateIngredient:
    name: str
    unit: str
    reorder_threshold: Decimal
    is_active: bool


@dataclass(frozen=True, slots=True)
class ChangeStock:
    kind: str
    quantity: Decimal
    reason: str
    expected_version: int | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class IngredientView:
    id: int
    restaurant_id: int
    name: str
    unit: str
    reorder_threshold: Decimal
    is_active: bool
    quantity: Decimal
    version: int
    low_stock: bool
