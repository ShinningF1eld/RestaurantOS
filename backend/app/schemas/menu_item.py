from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class MenuItemCreate(BaseModel):
    name: str
    description: str | None = None
    price: Decimal
    is_available: bool = True


class MenuItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    is_available: bool | None = None


class MenuItemResponse(BaseModel):
    menu_item_id: int
    menu_id: int
    name: str
    description: str | None = None
    price: Decimal
    is_available: bool

    model_config = ConfigDict(from_attributes=True)