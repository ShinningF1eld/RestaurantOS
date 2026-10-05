from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class IngredientFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    unit: Literal["g", "ml", "piece"]
    reorder_threshold: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=Decimal("999999999.999"),
        decimal_places=3,
        allow_inf_nan=False,
    )

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class IngredientCreate(IngredientFields):
    opening_quantity: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=Decimal("999999999.999"),
        decimal_places=3,
        allow_inf_nan=False,
    )
    idempotency_key: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"
    )


class IngredientUpdate(IngredientFields):
    is_active: bool = True


class StockChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["receipt", "waste", "count"]
    quantity: Decimal = Field(
        ge=0, le=Decimal("999999999.999"), decimal_places=3, allow_inf_nan=False
    )
    reason: str = Field(min_length=1, max_length=500)
    expected_version: int | None = Field(default=None, ge=0)
    idempotency_key: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"
    )

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Reason is required")
        return value


class IngredientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    restaurant_id: int
    name: str
    unit: str
    reorder_threshold: Decimal
    is_active: bool
    quantity: Decimal
    version: int
    low_stock: bool


class MovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ingredient_id: int
    kind: str
    quantity_delta: Decimal
    balance_after: Decimal
    version_after: int
    actor_user_id: UUID | None
    actor_name: str | None = None
    reason: str
    occurred_at: datetime
