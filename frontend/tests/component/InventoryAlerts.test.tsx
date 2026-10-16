import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import InventoryAlerts from "@/features/inventory/InventoryAlerts";
import { ApiError } from "@/lib/api/errors";

const api = vi.hoisted(() => ({ alerts: vi.fn(), alertHistory: vi.fn() }));
vi.mock("@/lib/api/inventory", () => ({ inventoryApi: () => api }));
const row = {
  episode_id: "episode-1",
  ingredient_id: 1,
  ingredient_name: "Rice",
  unit: "g",
  quantity: "2.000",
  reorder_threshold: "5.000",
  opened_at: "2026-10-15T00:00:00Z",
  notification_suppressed: false,
};
const page = { items: [row], total: 1, limit: 20, offset: 0 };
const flush = async () => {
  await act(async () => {
    await Promise.resolve();
  });
};

describe("InventoryAlerts", () => {
  beforeEach(() => {
    api.alerts.mockReset().mockResolvedValue(page);
    api.alertHistory.mockReset().mockResolvedValue({
      ...page,
      items: [
        {
          ...row,
          opening_quantity: "2.000",
          opening_threshold: "5.000",
          opening_source: "maintenance_initialization",
          notification_suppressed: true,
          resolved_at: null,
          resolution_reason: null,
        },
      ],
    });
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls at 15 seconds only when visible and refreshes after a local action", async () => {
    vi.useFakeTimers();
    const onAccessLost = vi.fn();
    const view = render(
      <InventoryAlerts restaurantId={1} refreshToken={0} onAccessLost={onAccessLost} />,
    );
    await flush();
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(api.alerts).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(api.alerts).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    fireEvent(document, new Event("visibilitychange"));
    await flush();
    expect(api.alerts).toHaveBeenCalledTimes(3);
    view.rerender(
      <InventoryAlerts restaurantId={1} refreshToken={1} onAccessLost={onAccessLost} />,
    );
    await flush();
    expect(api.alerts).toHaveBeenCalledTimes(4);
    expect(api.alertHistory).not.toHaveBeenCalled();
  });

  it("keeps stale data on errors and retries without claiming an empty result", async () => {
    render(<InventoryAlerts restaurantId={1} refreshToken={0} onAccessLost={vi.fn()} />);
    expect(await screen.findByText("Rice")).toBeVisible();
    api.alerts.mockRejectedValueOnce(new Error("Offline"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh alerts" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Last-known data");
    expect(screen.getByText("Rice")).toBeVisible();
    expect(screen.queryByText(/No active alerts/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry alerts" }));
    await flush();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("distinguishes initial errors and loads paginated history only when expanded", async () => {
    api.alerts.mockRejectedValueOnce(new Error("Offline"));
    render(<InventoryAlerts restaurantId={1} refreshToken={0} onAccessLost={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load data");
    expect(screen.queryByText(/No active alerts/)).not.toBeInTheDocument();
    api.alertHistory.mockResolvedValueOnce({
      ...page,
      total: 21,
      items: [
        {
          ...row,
          opening_quantity: "2.000",
          opening_threshold: "5.000",
          opening_source: "maintenance_initialization",
          resolved_at: null,
          resolution_reason: null,
        },
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: "Alert history" }));
    expect(await screen.findByText(/Low when tracking started/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next alert history" }));
    await flush();
    expect(api.alertHistory).toHaveBeenLastCalledWith(20, expect.any(AbortSignal));
  });

  it("ignores late responses after a newer refresh and notifies the parent on access loss", async () => {
    vi.useFakeTimers();
    let resolveOld!: (value: typeof page) => void;
    api.alerts.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
    );
    const denied = vi.fn();
    render(<InventoryAlerts restaurantId={1} refreshToken={0} onAccessLost={denied} />);
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(screen.getByText("Rice")).toBeVisible();
    await act(async () => {
      resolveOld({ ...page, items: [{ ...row, ingredient_name: "Obsolete" }] });
    });
    expect(screen.queryByText("Obsolete")).not.toBeInTheDocument();
    api.alerts.mockRejectedValueOnce(new ApiError("Forbidden", 403));
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(denied).toHaveBeenCalledOnce();
    expect(screen.queryByText("Rice")).not.toBeInTheDocument();
  });
});
