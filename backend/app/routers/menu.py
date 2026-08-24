from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models.menu import Menu
from app.db.models.restaurant import Restaurant
from app.schemas.menu import MenuCreate, MenuUpdate, MenuResponse


router = APIRouter(
    tags=["Menus"],
)


@router.post(
    "/restaurants/{restaurant_id}/menus",
    response_model=MenuResponse,
)
async def create_menu(
    restaurant_id: int,
    menu_data: MenuCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Restaurant).where(
            Restaurant.id == restaurant_id
        )
    )

    restaurant = result.scalar_one_or_none()

    if restaurant is None:
        raise HTTPException(
            status_code=404,
            detail="Restaurant not found",
        )

    menu = Menu(
        restaurant_id=restaurant_id,
        name=menu_data.name,
        description=menu_data.description,
    )

    db.add(menu)
    await db.commit()
    await db.refresh(menu)

    return menu


@router.get(
    "/restaurants/{restaurant_id}/menus",
    response_model=list[MenuResponse],
)
async def get_restaurant_menus(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id
        )
    )

    return result.scalars().all()


@router.get(
    "/menus/{menu_id}",
    response_model=MenuResponse,
)
async def get_menu(
    menu_id: int,
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

    return menu


@router.put(
    "/menus/{menu_id}",
    response_model=MenuResponse,
)
async def update_menu(
    menu_id: int,
    menu_data: MenuUpdate,
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

    if menu_data.name is not None:
        menu.name = menu_data.name

    if menu_data.description is not None:
        menu.description = menu_data.description

    await db.commit()
    await db.refresh(menu)

    return menu


@router.delete("/menus/{menu_id}")
async def delete_menu(
    menu_id: int,
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

    await db.delete(menu)
    await db.commit()

    return {
        "message": "Menu deleted successfully"
    }