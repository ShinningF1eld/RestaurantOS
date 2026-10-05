import type { Ingredient } from "./inventory";

export interface RecipeComponent {
  ingredient_id: number;
  ingredient_name: string;
  quantity: string;
  unit: Ingredient["unit"];
}

export interface Recipe {
  menu_item_id: number;
  restaurant_id: number;
  inventory_tracking: boolean;
  components: RecipeComponent[];
}

export interface RecipeUpdate {
  inventory_tracking: boolean;
  components: { ingredient_id: number; quantity: string }[];
}
