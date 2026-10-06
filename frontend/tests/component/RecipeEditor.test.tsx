import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RecipeEditor from "@/components/menu/RecipeEditor";
import { getRecipe, updateRecipe } from "@/lib/api/recipe";
import type { Ingredient } from "@/types/inventory";
import type { Recipe } from "@/types/recipe";

const inventory = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/lib/api/inventory", () => ({ inventoryApi: vi.fn(() => inventory) }));
vi.mock("@/lib/api/recipe", () => ({ getRecipe: vi.fn(), updateRecipe: vi.fn() }));

const item = {
  menu_item_id: 4,
  menu_id: 2,
  name: "Chicken rice",
  description: null,
  price: 12.5,
  is_available: true,
  inventory_tracking: false,
  out_of_stock: false,
  available_portions: null,
};
const chicken: Ingredient = {
  id: 11,
  restaurant_id: 17,
  name: "Chicken",
  unit: "g",
  reorder_threshold: "20.000",
  is_active: true,
  quantity: "500.000",
  version: 1,
  low_stock: false,
};

describe("RecipeEditor", () => {
  beforeEach(() => {
    inventory.list.mockReset().mockResolvedValue([chicken]);
    vi.mocked(getRecipe).mockReset().mockResolvedValue({
      menu_item_id: 4,
      restaurant_id: 17,
      inventory_tracking: false,
      components: [],
    });
    vi.mocked(updateRecipe).mockReset();
  });

  it("loads ingredients, validates stock tracking, and saves the chosen recipe", async () => {
    const onSaved = vi.fn();
    vi.mocked(updateRecipe).mockResolvedValueOnce({
      menu_item_id: 4,
      restaurant_id: 17,
      inventory_tracking: true,
      components: [],
    } as Recipe);
    render(<RecipeEditor item={item} onClose={vi.fn()} onSaved={onSaved} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading recipe and ingredients");
    await screen.findByText("No ingredients in this recipe yet.");

    fireEvent.click(screen.getByRole("checkbox", { name: /Track ingredient stock/ }));
    fireEvent.submit(screen.getByRole("button", { name: "Save recipe" }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Add at least one ingredient");
    expect(updateRecipe).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Add recipe ingredient" }));
    fireEvent.change(screen.getByLabelText("Recipe quantity 1"), { target: { value: "125" } });
    fireEvent.submit(screen.getByRole("button", { name: "Save recipe" }).closest("form")!);

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(updateRecipe).toHaveBeenCalledWith(4, {
      inventory_tracking: true,
      components: [{ ingredient_id: 11, quantity: "125" }],
    });
  });

  it("keeps load failures visible and offers a link when no active ingredients exist", async () => {
    vi.mocked(getRecipe).mockRejectedValueOnce(new Error("Recipe access denied."));
    const failed = render(<RecipeEditor item={item} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Recipe access denied.");
    failed.unmount();

    vi.mocked(getRecipe).mockResolvedValueOnce({
      menu_item_id: 4,
      restaurant_id: 17,
      inventory_tracking: false,
      components: [],
    });
    inventory.list.mockResolvedValueOnce([]);
    render(<RecipeEditor item={item} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(await screen.findByText(/No active ingredients are available/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Create ingredients in inventory/ })).toHaveAttribute(
      "href",
      "/restaurants/17/inventory",
    );
    expect(screen.getByRole("button", { name: "Add recipe ingredient" })).toBeDisabled();
  });
});
