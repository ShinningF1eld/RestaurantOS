from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models.menu import Menu
from app.db.models.menu_items import MenuItem
from app.schemas.menu_item import (
    MenuItemCreate,
    MenuItemUpdate,
    MenuItemResponse,
)


router = APIRouter(
    tags=["Menu Items"],
)


@router.post(
    "/menus/{menu_id}/items",
    response_model=MenuItemResponse,
)
async def create_menu_item(
    menu_id: int,
    item_data: MenuItemCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Menu).where(
            Menu.menu_id == menu_id
        )
    )

    menu = result.scalar_one_or_none()

    if menu is None:
        raise HTTPException(
            status_code=404,
            detail="Menu not found",
        )

    menu_item = MenuItem(
        menu_id=menu_id,
        name=item_data.name,
        description=item_data.description,
        price=item_data.price,
        is_available=item_data.is_available,
    )

    db.add(menu_item)
    await db.commit()
    await db.refresh(menu_item)

    return menu_item


@router.get(
    "/menus/{menu_id}/items",
    response_model=list[MenuItemResponse],
)
async def get_menu_items(
    menu_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MenuItem).where(
            MenuItem.menu_id == menu_id
        )
    )

    return result.scalars().all()


@router.get(
    "/menu-items/{menu_item_id}",
    response_model=MenuItemResponse,
)
async def get_menu_item(
    menu_item_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MenuItem).where(
            MenuItem.menu_item_id == menu_item_id
        )
    )

    menu_item = result.scalar_one_or_none()

    if menu_item is None:
        raise HTTPException(
            status_code=404,
            detail="Menu item not found",
        )

    return menu_item


@router.put(
    "/menu-items/{menu_item_id}",
    response_model=MenuItemResponse,
)
async def update_menu_item(
    menu_item_id: int,
    item_data: MenuItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MenuItem).where(
            MenuItem.menu_item_id == menu_item_id
        )
    )

    menu_item = result.scalar_one_or_none()

    if menu_item is None:
        raise HTTPException(
            status_code=404,
            detail="Menu item not found",
        )

    if item_data.name is not None:
        menu_item.name = item_data.name

    if item_data.description is not None:
        menu_item.description = item_data.description

    if item_data.price is not None:
        menu_item.price = item_data.price

    if item_data.is_available is not None:
        menu_item.is_available = item_data.is_available

    await db.commit()
    await db.refresh(menu_item)

    return menu_item


@router.delete("/menu-items/{menu_item_id}")
async def delete_menu_item(
    menu_item_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MenuItem).where(
            MenuItem.menu_item_id == menu_item_id
        )
    )

    menu_item = result.scalar_one_or_none()

    if menu_item is None:
        raise HTTPException(
            status_code=404,
            detail="Menu item not found",
        )

    await db.delete(menu_item)
    await db.commit()

    return {
        "message": "Menu item deleted successfully"
    }