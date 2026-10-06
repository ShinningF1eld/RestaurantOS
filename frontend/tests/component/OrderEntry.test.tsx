import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OrderEntry from "@/app/restaurants/[restaurant_id]/orders/OrderEntry";
import type { MenuItem } from "@/types/menu_item";
import { createOrder } from "@/lib/api/order";

const { router } = vi.hoisted(() => ({ router: { refresh: vi.fn(), push: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/features/inventory/useStockRefresh", () => ({ useStockRefresh: vi.fn() }));
vi.mock("@/lib/api/order", () => ({ createOrder: vi.fn() }));

const available: MenuItem = {
  menu_item_id: 4,
  menu_id: 2,
  name: "Chicken rice",
  description: null,
  price: 12.5,
  is_available: true,
  inventory_tracking: true,
  out_of_stock: false,
  available_portions: 3,
};

describe("OrderEntry", () => {
  beforeEach(() => {
    vi.mocked(createOrder).mockReset();
    router.refresh.mockClear();
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn().mockReturnValueOnce("order-key-1").mockReturnValue("order-key-next"),
    });
  });

  it("shows an empty catalog and keeps order submission unavailable", () => {
    render(<OrderEntry restaurantId={17} items={[]} />);
    expect(
      screen.getByText("There are no available menu items. Add or enable one in the menu first."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create order" })).toBeDisabled();
  });

  it("checks the current stock snapshot before sending an order", async () => {
    render(<OrderEntry restaurantId={17} items={[available]} />);
    fireEvent.change(screen.getByLabelText("Quantity for Chicken rice"), {
      target: { value: "4" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Create order" }).closest("form")!);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "There is not enough ingredient stock",
    );
    expect(createOrder).not.toHaveBeenCalled();
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("reuses an order key after an ambiguous failure and clears the form after success", async () => {
    vi.mocked(createOrder)
      .mockRejectedValueOnce(new Error("Lost response after commit"))
      .mockResolvedValueOnce({} as Awaited<ReturnType<typeof createOrder>>);
    render(<OrderEntry restaurantId={17} items={[available]} />);
    fireEvent.change(screen.getByLabelText("Quantity for Chicken rice"), {
      target: { value: "2" },
    });
    fireEvent.change(screen.getByPlaceholderText("Table number (optional)"), {
      target: { value: "12" },
    });
    fireEvent.change(screen.getByPlaceholderText("Customer name (optional)"), {
      target: { value: "Mali" },
    });
    const submit = screen.getByRole("button", { name: "Create order" });

    fireEvent.submit(submit.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Lost response after commit");
    fireEvent.submit(submit.closest("form")!);

    await screen.findByDisplayValue("0");
    const first = vi.mocked(createOrder).mock.calls[0]![1];
    const retry = vi.mocked(createOrder).mock.calls[1]![1];
    expect(first).toMatchObject({
      table_number: "12",
      customer_name: "Mali",
      items: [{ menu_item_id: 4, quantity: 2 }],
    });
    expect(retry.idempotency_key).toBe(first.idempotency_key);
    expect(retry.idempotency_key).toBe("order-key-1");
    expect(screen.getByPlaceholderText("Table number (optional)")).toHaveValue("");
    expect(screen.getByPlaceholderText("Customer name (optional)")).toHaveValue("");
    expect(router.refresh).toHaveBeenCalledTimes(2);
  });
});
