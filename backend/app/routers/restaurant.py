from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.restaurant import RestaurantCreate, RestaurantResponse, RestaurantUpdate
from app.services.restaurant import CreateRestaurant, RestaurantService, UpdateRestaurant


router = APIRouter(prefix="/api/restaurants", tags=["restaurants"])


@router.post("", response_model=RestaurantResponse, status_code=status.HTTP_201_CREATED)
async def create_restaurant(
    restaurant: RestaurantCreate, db: AsyncSession = Depends(get_db)
) -> RestaurantResponse:
    created = await RestaurantService(db).create(
        CreateRestaurant(
            name=restaurant.name,
            address=restaurant.address,
            phone=restaurant.phone,
        )
    )
    return RestaurantResponse.model_validate(created)


@router.get("", response_model=list[RestaurantResponse])
async def get_restaurants(
    db: AsyncSession = Depends(get_db),
) -> list[RestaurantResponse]:
    restaurants = await RestaurantService(db).list_all()
    return [RestaurantResponse.model_validate(restaurant) for restaurant in restaurants]


@router.get("/{restaurant_id}", response_model=RestaurantResponse)
async def get_restaurant(
    restaurant_id: int, db: AsyncSession = Depends(get_db)
) -> RestaurantResponse:
    restaurant = await RestaurantService(db).get(restaurant_id)
    return RestaurantResponse.model_validate(restaurant)


@router.put("/{restaurant_id}", response_model=RestaurantResponse)
async def update_restaurant(
    restaurant_id: int,
    restaurant_data: RestaurantUpdate,
    db: AsyncSession = Depends(get_db),
) -> RestaurantResponse:
    updated = await RestaurantService(db).update(
        restaurant_id,
        UpdateRestaurant(
            name=restaurant_data.name,
            address=restaurant_data.address,
            phone=restaurant_data.phone,
            fields=frozenset(restaurant_data.model_fields_set),
        ),
    )
    return RestaurantResponse.model_validate(updated)


@router.delete("/{restaurant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_restaurant(
    restaurant_id: int, db: AsyncSession = Depends(get_db)
) -> None:
    await RestaurantService(db).delete(restaurant_id)
