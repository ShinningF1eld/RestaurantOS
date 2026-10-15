import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import InventoryManager from "@/features/inventory/InventoryManager";
import type { Ingredient } from "@/types/inventory";
import { ApiError } from "@/lib/api/errors";

const inventory = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  stock: vi.fn(),
  history: vi.fn(),
  alerts: vi.fn(),
  alertHistory: vi.fn(),
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
    inventory.alerts.mockReset().mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    inventory.alertHistory
      .mockReset()
      .mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    inventory.list.mockReset().mockResolvedValue([rice]);
    inventory.create.mockReset();
    inventory.update.mockReset();
    inventory.stock.mockReset();
    inventory.history.mockReset();
  });

  it("preserves focused editor values across the visible 15-second refresh", async () => {
    vi.useFakeTimers();
    try {
      render(<InventoryManager restaurantId={17} canManage />);
      await act(async () => {
        await Promise.resolve();
      });
      expect(screen.getByText("Rice")).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: "Edit Rice" }));
      const input = screen.getByLabelText("Ingredient name");
      fireEvent.change(input, { target: { value: "Unsubmitted name" } });
      input.focus();
      inventory.list.mockResolvedValue([{ ...rice, quantity: "400.000" }]);
      await act(async () => {
        vi.advanceTimersByTime(15_000);
      });
      expect(inventory.list).toHaveBeenCalledTimes(2);
      expect(input).toHaveValue("Unsubmitted name");
      expect(input).toHaveFocus();
    } finally {
      vi.useRealTimers();
    }
  });

  it("clears scoped data on access loss and stops subsequent polling", async () => {
    vi.useFakeTimers();
    try {
      render(<InventoryManager restaurantId={17} canManage />);
      await act(async () => {
        await Promise.resolve();
      });
      inventory.alerts.mockRejectedValueOnce(new ApiError("Forbidden", 403));
      fireEvent.click(screen.getByRole("button", { name: "Refresh alerts" }));
      await act(async () => {
        await Promise.resolve();
      });
      expect(screen.getByRole("alert")).toHaveTextContent("Inventory is unavailable");
      expect(screen.queryByText("Rice")).not.toBeInTheDocument();
      const calls = inventory.alerts.mock.calls.length;
      await act(async () => {
        vi.advanceTimersByTime(30_000);
      });
      expect(inventory.alerts).toHaveBeenCalledTimes(calls);
    } finally {
      vi.useRealTimers();
    }
  });

  it("discards previous restaurant state and its late inventory response", async () => {
    let resolveOld!: (rows: Ingredient[]) => void;
    inventory.list.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
    );
    const view = render(<InventoryManager restaurantId={17} canManage />);
    await act(async () => {
      await Promise.resolve();
    });
    inventory.list.mockResolvedValue([
      { ...rice, id: 10, restaurant_id: 18, name: "New branch flour" },
    ]);
    view.rerender(<InventoryManager restaurantId={18} canManage />);
    await screen.findByText("New branch flour");
    await act(async () => {
      resolveOld([rice]);
    });
    expect(screen.queryByText("Rice")).not.toBeInTheDocument();
    expect(screen.getByText("New branch flour")).toBeVisible();
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

    expect(await screen.findByText("Ingredient saved.")).toHaveAttribute("role", "status");
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
