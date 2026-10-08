from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.modules.auth.dependencies import get_current_principal
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.catalog.menu_schemas import MenuCreate, MenuResponse, MenuUpdate
from app.modules.catalog.service import CatalogService, CreateMenu, UpdateMenu


router = APIRouter(tags=["Menus"])


@router.post("/restaurants/{restaurant_id}/menus", response_model=MenuResponse)
async def create_menu(
    restaurant_id: int,
    menu_data: MenuCreate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> MenuResponse:
    menu = await CatalogService(db, principal).create_menu(
        restaurant_id,
        CreateMenu(name=menu_data.name, description=menu_data.description),
    )
    return MenuResponse.model_validate(menu)


@router.get("/restaurants/{restaurant_id}/menus", response_model=list[MenuResponse])
async def get_restaurant_menus(
    restaurant_id: int,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[MenuResponse]:
    menus = await CatalogService(
        db,
        principal,
        menu_cache=request.app.state.catalog_menu_cache,
        redis=request.app.state.redis,
    ).list_menus(restaurant_id)
    return [MenuResponse.model_validate(menu) for menu in menus]


@router.get("/menus/{menu_id}", response_model=MenuResponse)
async def get_menu(
    menu_id: int,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> MenuResponse:
    menu = await CatalogService(db, principal).get_menu(menu_id)
    return MenuResponse.model_validate(menu)


@router.put("/menus/{menu_id}", response_model=MenuResponse)
async def update_menu(
    menu_id: int,
    menu_data: MenuUpdate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> MenuResponse:
    menu = await CatalogService(db, principal).update_menu(
        menu_id,
        UpdateMenu(name=menu_data.name, description=menu_data.description),
    )
    return MenuResponse.model_validate(menu)


@router.delete("/menus/{menu_id}")
async def delete_menu(
    menu_id: int,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await CatalogService(db, principal).delete_menu(menu_id)
    return {"message": "Menu deleted successfully"}
