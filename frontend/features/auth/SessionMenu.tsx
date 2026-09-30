"use client";

import { useEffect, useState } from "react";
import { currentUser, logout, subscribeSession } from "@/lib/api/client";

export default function SessionMenu() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let mounted = true;
    void currentUser().then(user => { if (mounted) setEmail(user.email); }).catch(() => {});
    const unsubscribe = subscribeSession(status => {
      if (status === "signed-out") window.location.replace("/login");
      // Identity can change in another tab. Full navigation drops stale RSC data.
      else window.location.reload();
    });
    const restore = (event: PageTransitionEvent) => { if (event.persisted) window.location.reload(); };
    window.addEventListener("pageshow", restore);
    return () => { mounted = false; unsubscribe(); window.removeEventListener("pageshow", restore); };
  }, []);

  async function signOut() {
    setBusy(true);
    setError("");
    try {
      await logout();
      window.location.replace("/login");
    } catch {
      setError("Sign out failed. Please try again.");
      setBusy(false);
    }
  }
  return <div className="flex flex-wrap items-center justify-end gap-3 text-sm">
    <span className="text-slate-600">{email}</span>
    <button onClick={signOut} disabled={busy} className="rounded-md border border-slate-300 bg-white px-3 py-2 font-semibold disabled:opacity-50">{busy ? "Signing out…" : "Sign out"}</button>
    {error && <p role="alert" className="text-red-700">{error}</p>}
  </div>;
}
