import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import OrderActions from "@/app/restaurants/[restaurant_id]/orders/OrderActions";
import type { AccessContext } from "@/types/access";
import { updateOrder } from "@/lib/api/order";

const { router } = vi.hoisted(() => ({ router: { refresh: vi.fn(), push: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/lib/api/order", () => ({ cancelOrder: vi.fn(), updateOrder: vi.fn() }));

const access = (role: AccessContext["role"]): AccessContext => ({
  organization_id: "org-test",
  organization_number: 1,
  role,
  capabilities: ["order.status.update", "order.cancel"],
  restaurant_ids: [17],
});

describe("OrderActions", () => {
  it("limits employee transitions while retaining the permitted cancel action", () => {
    render(<OrderActions orderId={8} status="SUBMITTED" access={access("EMPLOYEE")} />);
    expect(screen.queryByRole("button", { name: "Mark accepted" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("shows authorized manager transitions and reports write failures", async () => {
    vi.mocked(updateOrder).mockRejectedValueOnce(new Error("Order changed. Refresh and retry."));
    render(<OrderActions orderId={8} status="SUBMITTED" access={access("MANAGER")} />);

    fireEvent.click(screen.getByRole("button", { name: "Mark accepted" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Order changed. Refresh and retry.");
    expect(updateOrder).toHaveBeenCalledWith(8, { status: "ACCEPTED" });
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });
});
