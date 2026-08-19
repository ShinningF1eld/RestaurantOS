from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models.restaurant import Restaurant
from app.schemas.restaurant import (
    RestaurantCreate,
    RestaurantResponse,
    RestaurantUpdate,
)

router = APIRouter(
    prefix="/api/restaurants",
    tags=["restaurants"],
)


@router.post(
    "",
    response_model=RestaurantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_restaurant(
    restaurant: RestaurantCreate,
    db: AsyncSession = Depends(get_db),
):
    new_restaurant = Restaurant(
        name=restaurant.name,
        address=restaurant.address,
        phone=restaurant.phone,
    )

    db.add(new_restaurant)
    await db.commit()
    await db.refresh(new_restaurant)

    return new_restaurant


@router.get(
    "",
    response_model=list[RestaurantResponse],
)
async def get_restaurants(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Restaurant)
    )

    return result.scalars().all()


@router.get(
    "/{restaurant_id}",
    response_model=RestaurantResponse,
)
async def get_restaurant(
    restaurant_id: int,
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

    return restaurant


@router.put(
    "/{restaurant_id}",
    response_model=RestaurantResponse,
)
async def update_restaurant(
    restaurant_id: int,
    restaurant_data: RestaurantUpdate,
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

    update_data = restaurant_data.model_dump(
        exclude_unset=True
    )

    for field, value in update_data.items():
        setattr(restaurant, field, value)

    await db.commit()
    await db.refresh(restaurant)

    return restaurant


@router.delete(
    "/{restaurant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_restaurant(
    restaurant_id: int,
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

    await db.delete(restaurant)
    await db.commit()