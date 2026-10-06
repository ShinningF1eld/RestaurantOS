import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LoginForm from "@/features/auth/LoginForm";
import { login } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({ login: vi.fn() }));

describe("LoginForm", () => {
  beforeEach(() => vi.mocked(login).mockReset());

  it("submits the entered credentials and shows a recoverable error", async () => {
    let rejectLogin!: (reason: Error) => void;
    vi.mocked(login).mockImplementationOnce(
      () =>
        new Promise<Awaited<ReturnType<typeof login>>>((_resolve, reject) => {
          rejectLogin = reject;
        }),
    );
    render(<LoginForm next="/restaurants/17/orders" />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "owner@example.test" } });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "synthetic-password" },
    });
    const button = screen.getByRole("button", { name: "Sign in" });
    fireEvent.submit(button.closest("form")!);

    expect(login).toHaveBeenCalledWith("owner@example.test", "synthetic-password");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Signing in…");
    rejectLogin(new Error("The email or password is incorrect."));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The email or password is incorrect.",
    );
    expect(button).toBeEnabled();
    expect(button).toHaveTextContent("Sign in");
  });
});
