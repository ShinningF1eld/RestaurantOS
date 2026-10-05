export type Ingredient = {
  id: number; restaurant_id: number; name: string; unit: "g" | "ml" | "piece";
  reorder_threshold: string; is_active: boolean; quantity: string; version: number; low_stock: boolean;
};
export type Movement = {
  id: number; ingredient_id: number; kind: string; quantity_delta: string;
  balance_after: string; version_after: number; actor_user_id: string | null;
  actor_name: string | null; reason: string; occurred_at: string;
};
