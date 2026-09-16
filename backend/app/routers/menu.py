from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.menu import MenuCreate, MenuResponse, MenuUpdate
from app.services.catalog import CatalogService, CreateMenu, UpdateMenu


router = APIRouter(tags=["Menus"])


@router.post("/restaurants/{restaurant_id}/menus", response_model=MenuResponse)
async def create_menu(
    restaurant_id: int,
    menu_data: MenuCreate,
    db: AsyncSession = Depends(get_db),
) -> MenuResponse:
    menu = await CatalogService(db).create_menu(
        restaurant_id,
        CreateMenu(name=menu_data.name, description=menu_data.description),
    )
    return MenuResponse.model_validate(menu)


@router.get("/restaurants/{restaurant_id}/menus", response_model=list[MenuResponse])
async def get_restaurant_menus(
    restaurant_id: int, db: AsyncSession = Depends(get_db)
) -> list[MenuResponse]:
    menus = await CatalogService(db).list_menus(restaurant_id)
    return [MenuResponse.model_validate(menu) for menu in menus]


@router.get("/menus/{menu_id}", response_model=MenuResponse)
async def get_menu(menu_id: int, db: AsyncSession = Depends(get_db)) -> MenuResponse:
    menu = await CatalogService(db).get_menu(menu_id)
    return MenuResponse.model_validate(menu)


@router.put("/menus/{menu_id}", response_model=MenuResponse)
async def update_menu(
    menu_id: int,
    menu_data: MenuUpdate,
    db: AsyncSession = Depends(get_db),
) -> MenuResponse:
    menu = await CatalogService(db).update_menu(
        menu_id,
        UpdateMenu(name=menu_data.name, description=menu_data.description),
    )
    return MenuResponse.model_validate(menu)


@router.delete("/menus/{menu_id}")
async def delete_menu(menu_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await CatalogService(db).delete_menu(menu_id)
    return {"message": "Menu deleted successfully"}
