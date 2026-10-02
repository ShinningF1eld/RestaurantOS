from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RestaurantBase(BaseModel):
    name: str
    address: str | None = None
    phone: str | None = None


class RestaurantCreate(RestaurantBase):
    model_config = ConfigDict(extra="forbid")


class RestaurantUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    phone: str | None = None


class RestaurantResponse(RestaurantBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
