export type Ingredient = {
  id: number;
  restaurant_id: number;
  name: string;
  unit: "g" | "ml" | "piece";
  reorder_threshold: string;
  is_active: boolean;
  quantity: string;
  version: number;
  low_stock: boolean;
};
export type Movement = {
  id: number;
  ingredient_id: number;
  kind: string;
  quantity_delta: string;
  balance_after: string;
  version_after: number;
  actor_user_id: string | null;
  actor_name: string | null;
  reason: string;
  occurred_at: string;
};

export type ActiveAlert = {
  episode_id: string;
  ingredient_id: number;
  ingredient_name: string;
  unit: Ingredient["unit"];
  quantity: string;
  reorder_threshold: string;
  opened_at: string;
  notification_suppressed: boolean;
};
export type AlertHistory = {
  episode_id: string;
  ingredient_id: number;
  ingredient_name: string;
  unit: Ingredient["unit"];
  opening_quantity: string;
  opening_threshold: string;
  opened_at: string;
  opening_source: string;
  notification_suppressed: boolean;
  resolved_at: string | null;
  resolution_reason: "stock_recovered" | "threshold_changed" | "archived" | null;
};
export type AlertPage<T> = { items: T[]; total: number; limit: number; offset: number };
