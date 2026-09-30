"use client";

import { useState, type FormEvent } from "react";
import { login } from "@/lib/api/client";
import { safeReturnPath } from "./paths";

export default function LoginForm({ next }: { next: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await login(String(data.get("email")), String(data.get("password")));
      sessionStorage.removeItem("ros-renew-attempt");
      window.location.replace(safeReturnPath(next));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Sign in failed. Please try again.");
      setBusy(false);
    }
  }

  return <form onSubmit={submit} className="space-y-5">
    <div><label htmlFor="email" className="block text-sm font-semibold">Email</label>
      <input id="email" name="email" type="email" autoComplete="username" required maxLength={254} className="mt-2 w-full rounded-md border border-slate-300 p-3" /></div>
    <div><label htmlFor="password" className="block text-sm font-semibold">Password</label>
      <input id="password" name="password" type="password" autoComplete="current-password" required maxLength={128} className="mt-2 w-full rounded-md border border-slate-300 p-3" /></div>
    {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    <button disabled={busy} className="w-full rounded-md bg-slate-950 px-4 py-3 font-semibold text-white disabled:opacity-50">{busy ? "Signing in…" : "Sign in"}</button>
  </form>;
}
