import { describe, expect, it } from "vitest";
import { loginPath, safeReturnPath } from "@/features/auth/paths";

describe("safe authentication return paths", () => {
  it("preserves supported workspace routes and only safe pagination", () => {
    expect(safeReturnPath("/restaurants/17/orders?offset=20&next=https://evil.example")).toBe(
      "/restaurants/17/orders?offset=20",
    );
    expect(loginPath("/restaurants/17/inventory")).toBe(
      "/login?next=%2Frestaurants%2F17%2Finventory",
    );
  });

  it.each([
    "https://evil.example/",
    "//evil.example/",
    "/restaurants/17/settings",
    "/restaurants/17/orders\\\\evil",
  ])("falls back for an unsafe destination: %s", (path) => {
    expect(safeReturnPath(path)).toBe("/dashboard/restaurants");
  });

  it("drops unsupported pagination without rejecting a safe route", () => {
    expect(safeReturnPath("/restaurants/17/orders?offset=-1")).toBe("/restaurants/17/orders");
  });
});
