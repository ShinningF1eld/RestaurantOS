import {
  Restaurant,
  RestaurantCreate,
  RestaurantUpdate,
} from "@/types/restaurant";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export async function getRestaurants(): Promise<Restaurant[]> {
  const response = await fetch(`${API_URL}/api/restaurants`);

  if (!response.ok) {
    throw new Error("Failed to fetch restaurants");
  }

  return response.json();
}

export async function getRestaurant(
  id: number
): Promise<Restaurant> {
  const response = await fetch(
    `${API_URL}/api/restaurants/${id}`
  );

  if (!response.ok) {
    throw new Error("Failed to fetch restaurant");
  }

  return response.json();
}

export async function createRestaurant(
  data: RestaurantCreate
): Promise<Restaurant> {
  const response = await fetch(
    `${API_URL}/api/restaurants`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    throw new Error("Failed to create restaurant");
  }

  return response.json();
}

export async function updateRestaurant(
  id: number,
  data: RestaurantUpdate
): Promise<Restaurant> {
  const response = await fetch(
    `${API_URL}/api/restaurants/${id}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    throw new Error("Failed to update restaurant");
  }

  return response.json();
}

export async function deleteRestaurant(
  id: number
): Promise<void> {
  const response = await fetch(
    `${API_URL}/api/restaurants/${id}`,
    {
      method: "DELETE",
    }
  );

  if (!response.ok) {
    throw new Error("Failed to delete restaurant");
  }
}