export interface Restaurant {
  id: number;
  name: string;
  address: string;
  phone: string;
}

export interface RestaurantCreate {
  name: string;
  address: string;
  phone: string;
}

export interface RestaurantUpdate {
  name?: string;
  address?: string;
  phone?: string;
}