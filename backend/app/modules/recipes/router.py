"""Recipe configuration routes for menu items."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.modules.auth.dependencies import get_current_principal
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.recipes.domain.commands import (
    RecipeComponentInput,
    ReplaceRecipe,
)
from app.modules.recipes.schemas import RecipeReplaceRequest, RecipeResponse
from app.modules.recipes.service import RecipesService


router = APIRouter(tags=["Recipes"])


@router.get("/menu-items/{menu_item_id}/recipe", response_model=RecipeResponse)
async def get_recipe(
    menu_item_id: int,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> RecipeResponse:
    return RecipeResponse.model_validate(
        await RecipesService(db, principal).get(menu_item_id)
    )


@router.put("/menu-items/{menu_item_id}/recipe", response_model=RecipeResponse)
async def replace_recipe(
    menu_item_id: int,
    data: RecipeReplaceRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> RecipeResponse:
    command = ReplaceRecipe(
        inventory_tracking=data.inventory_tracking,
        components=tuple(
            RecipeComponentInput(
                ingredient_id=component.ingredient_id,
                quantity=component.quantity,
            )
            for component in data.components
        ),
    )
    return RecipeResponse.model_validate(
        await RecipesService(db, principal).replace(menu_item_id, command)
    )
