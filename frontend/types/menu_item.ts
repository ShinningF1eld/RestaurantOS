export interface MenuItem {
  menu_item_id: number;
  menu_id: number;
  name: string;
  description: string | null;
  price: number;
  is_available: boolean;
  inventory_tracking: boolean;
  out_of_stock: boolean;
  available_portions: number | null;
}

export interface MenuItemCreate {
  name: string;
  description?: string | null;
  price: number;
  is_available?: boolean;
}

export interface MenuItemUpdate {
  name?: string;
  description?: string | null;
  price?: number;
  is_available?: boolean;
}
