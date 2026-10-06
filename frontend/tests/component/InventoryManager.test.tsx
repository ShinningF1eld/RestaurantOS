import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import InventoryManager from "@/features/inventory/InventoryManager";
import type { Ingredient } from "@/types/inventory";

const inventory = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  stock: vi.fn(),
  history: vi.fn(),
}));
vi.mock("@/lib/api/inventory", () => ({ inventoryApi: vi.fn(() => inventory) }));

const rice: Ingredient = {
  id: 9,
  restaurant_id: 17,
  name: "Rice",
  unit: "g",
  reorder_threshold: "100.000",
  is_active: true,
  quantity: "500.000",
  version: 2,
  low_stock: false,
};

describe("InventoryManager", () => {
  beforeEach(() => {
    inventory.list.mockReset().mockResolvedValue([rice]);
    inventory.create.mockReset();
    inventory.update.mockReset();
    inventory.stock.mockReset();
    inventory.history.mockReset();
  });

  it("shows loading, then an empty inventory with the manager action", async () => {
    let resolveList!: (rows: Ingredient[]) => void;
    inventory.list.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveList = resolve;
      }),
    );
    render(<InventoryManager restaurantId={17} canManage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading inventory");
    resolveList([]);

    expect(await screen.findByText("No ingredients yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add first ingredient" })).toBeEnabled();
  });

  it("surfaces load errors and lets the user retry", async () => {
    inventory.list
      .mockRejectedValueOnce(new Error("Inventory service unavailable."))
      .mockResolvedValueOnce([rice]);
    render(<InventoryManager restaurantId={17} canManage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Inventory service unavailable.");
    fireEvent.click(screen.getByRole("button", { name: "Refresh inventory" }));
    expect(await screen.findByText("Rice")).toBeInTheDocument();
    expect(inventory.list).toHaveBeenCalledTimes(2);
  });

  it("saves a new ingredient with a stable idempotency key", async () => {
    inventory.create.mockResolvedValueOnce(rice);
    vi.stubGlobal("crypto", { randomUUID: vi.fn().mockReturnValue("ingredient-key-1") });
    render(<InventoryManager restaurantId={17} canManage />);
    await screen.findByText("Rice");
    fireEvent.click(screen.getByRole("button", { name: "Add ingredient" }));
    fireEvent.change(screen.getByLabelText("Ingredient name"), { target: { value: "Noodles" } });
    fireEvent.change(screen.getByLabelText("Opening stock"), { target: { value: "250" } });
    fireEvent.submit(screen.getByRole("button", { name: "Save ingredient" }).closest("form")!);

    expect(await screen.findByRole("status")).toHaveTextContent("Ingredient saved.");
    expect(inventory.create).toHaveBeenCalledWith({
      name: "Noodles",
      unit: "g",
      reorder_threshold: "0",
      opening_quantity: "250",
      idempotency_key: "ingredient-key-1",
    });
  });

  it("keeps read actions available and hides write controls for a read-only role", async () => {
    render(<InventoryManager restaurantId={17} canManage={false} />);
    expect(await screen.findByText("Rice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "History for Rice" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add ingredient" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add first ingredient" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit Rice" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Manage stock for Rice" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive Rice" })).not.toBeInTheDocument();
  });
});
