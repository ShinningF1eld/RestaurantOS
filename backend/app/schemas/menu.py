from pydantic import BaseModel, ConfigDict


class MenuCreate(BaseModel):
    name: str
    description: str | None = None


class MenuUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class MenuResponse(BaseModel):
    menu_id: int
    restaurant_id: int
    name: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)