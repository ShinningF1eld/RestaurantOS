from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.modules.auth.dependencies import get_current_principal
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.inventory.schemas import (
    IngredientCreate,
    IngredientUpdate,
    IngredientResponse,
    StockChange,
    MovementResponse,
)
from app.modules.inventory.service import InventoryService
from app.modules.inventory.domain.commands import (
    CreateIngredient,
    UpdateIngredient,
    ChangeStock,
)

router = APIRouter(
    prefix="/api/restaurants/{restaurant_id}/inventory", tags=["Inventory"]
)


@router.get("/ingredients", response_model=list[IngredientResponse])
async def ingredients(
    restaurant_id: int,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[IngredientResponse]:
    return [
        IngredientResponse.model_validate(row)
        for row in await InventoryService(db, principal).list_ingredients(
            restaurant_id, limit, offset
        )
    ]


@router.post("/ingredients", response_model=IngredientResponse, status_code=201)
async def create(
    restaurant_id: int,
    data: IngredientCreate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> IngredientResponse:
    return IngredientResponse.model_validate(
        await InventoryService(db, principal).create(
            restaurant_id, CreateIngredient(**data.model_dump())
        )
    )


@router.put("/ingredients/{ingredient_id}", response_model=IngredientResponse)
async def update(
    restaurant_id: int,
    ingredient_id: int,
    data: IngredientUpdate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> IngredientResponse:
    return IngredientResponse.model_validate(
        await InventoryService(db, principal).update(
            restaurant_id, ingredient_id, UpdateIngredient(**data.model_dump())
        )
    )


@router.post(
    "/ingredients/{ingredient_id}/movements",
    response_model=MovementResponse,
    status_code=201,
)
async def change(
    restaurant_id: int,
    ingredient_id: int,
    data: StockChange,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> MovementResponse:
    return MovementResponse.model_validate(
        await InventoryService(db, principal).change(
            restaurant_id, ingredient_id, ChangeStock(**data.model_dump())
        )
    )


@router.get(
    "/ingredients/{ingredient_id}/movements", response_model=list[MovementResponse]
)
async def history(
    restaurant_id: int,
    ingredient_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[MovementResponse]:
    rows = await InventoryService(db, principal).history(
        restaurant_id, ingredient_id, limit, offset
    )
    return [MovementResponse.model_validate(row) for row in rows]
