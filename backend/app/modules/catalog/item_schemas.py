from decimal import Decimal

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.modules.catalog.domain.policies import MAX_MENU_PRICE


MenuPrice = Annotated[
    Decimal, Field(ge=0, le=MAX_MENU_PRICE, max_digits=10, decimal_places=2)
]


class MenuItemCreate(BaseModel):
    name: str
    description: str | None = None
    price: MenuPrice
    is_available: bool = True


class MenuItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: MenuPrice | None = None
    is_available: bool | None = None


class MenuItemResponse(BaseModel):
    menu_item_id: int
    menu_id: int
    restaurant_id: int
    name: str
    description: str | None = None
    price: Decimal
    is_available: bool
    inventory_tracking: bool
    out_of_stock: bool
    available_portions: int | None

    model_config = ConfigDict(from_attributes=True)
