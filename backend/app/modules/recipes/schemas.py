"""HTTP schemas for replacing and reading complete menu recipes."""

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


RecipeQuantity = Annotated[
    Decimal,
    Field(
        gt=0,
        le=Decimal("999999999.999"),
        max_digits=12,
        decimal_places=3,
        allow_inf_nan=False,
    ),
]


class RecipeComponentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_id: int = Field(gt=0)
    quantity: RecipeQuantity

    @field_validator("quantity", mode="before")
    @classmethod
    def require_decimal_string(cls, value: object) -> Decimal:
        if not isinstance(value, str):
            raise ValueError("Quantity must be a decimal string")
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            raise ValueError("Quantity must be a valid decimal string") from None


class RecipeReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_tracking: bool
    components: list[RecipeComponentInput]


class RecipeComponentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ingredient_id: int
    ingredient_name: str
    unit: str
    quantity: Decimal


class RecipeResponse(BaseModel):
    menu_item_id: int
    restaurant_id: int
    inventory_tracking: bool
    components: list[RecipeComponentResponse]

    model_config = ConfigDict(from_attributes=True)
