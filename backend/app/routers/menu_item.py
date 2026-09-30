from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.menu_item import MenuItemCreate, MenuItemResponse, MenuItemUpdate
from app.services.catalog import CatalogService, CreateMenuItem, UpdateMenuItem


router = APIRouter(tags=["Menu Items"])


@router.post("/menus/{menu_id}/items", response_model=MenuItemResponse)
async def create_menu_item(
    menu_id: int,
    item_data: MenuItemCreate,
    db: AsyncSession = Depends(get_db),
) -> MenuItemResponse:
    menu_item = await CatalogService(db).create_menu_item(
        menu_id,
        CreateMenuItem(
            name=item_data.name,
            description=item_data.description,
            price=item_data.price,
            is_available=item_data.is_available,
        ),
    )
    return MenuItemResponse.model_validate(menu_item)


@router.get("/menus/{menu_id}/items", response_model=list[MenuItemResponse])
async def get_menu_items(
    menu_id: int, db: AsyncSession = Depends(get_db)
) -> list[MenuItemResponse]:
    menu_items = await CatalogService(db).list_menu_items(menu_id)
    return [MenuItemResponse.model_validate(menu_item) for menu_item in menu_items]


@router.get("/menu-items/{menu_item_id}", response_model=MenuItemResponse)
async def get_menu_item(
    menu_item_id: int, db: AsyncSession = Depends(get_db)
) -> MenuItemResponse:
    menu_item = await CatalogService(db).get_menu_item(menu_item_id)
    return MenuItemResponse.model_validate(menu_item)


@router.put("/menu-items/{menu_item_id}", response_model=MenuItemResponse)
async def update_menu_item(
    menu_item_id: int,
    item_data: MenuItemUpdate,
    db: AsyncSession = Depends(get_db),
) -> MenuItemResponse:
    menu_item = await CatalogService(db).update_menu_item(
        menu_item_id,
        UpdateMenuItem(
            name=item_data.name,
            description=item_data.description,
            price=item_data.price,
            is_available=item_data.is_available,
        ),
    )
    return MenuItemResponse.model_validate(menu_item)


@router.delete("/menu-items/{menu_item_id}")
async def delete_menu_item(
    menu_item_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    outcome = await CatalogService(db).delete_menu_item(menu_item_id)
    if outcome == "deactivated":
        return {"message": "Menu item deactivated because it has order history"}
    return {"message": "Menu item deleted successfully"}
