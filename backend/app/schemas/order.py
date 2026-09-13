from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrderItemCreate(BaseModel):
    menu_item_id: int
    quantity: int = Field(gt=0)
    notes: str | None = None


class OrderItemResponse(BaseModel):
    order_item_id: int
    order_id: int
    menu_item_id: int
    menu_item_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    table_number: str | None = None
    customer_name: str | None = None
    notes: str | None = None
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderUpdate(BaseModel):
    table_number: str | None = None
    customer_name: str | None = None
    status: str | None = None
    notes: str | None = None
    items: list[OrderItemCreate] | None = Field(default=None, min_length=1)


class OrderResponse(BaseModel):
    order_id: int
    restaurant_id: int
    table_number: str | None = None
    customer_name: str | None = None
    status: str
    notes: str | None = None
    subtotal: Decimal
    total: Decimal
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]

    model_config = ConfigDict(from_attributes=True)
