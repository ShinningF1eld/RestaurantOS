"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { renewSession } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { loginPath, safeReturnPath } from "./paths";

export default function RenewSession({ next }: { next: string }) {
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    const target = safeReturnPath(next);
    async function renew() {
      // Store only an attempt timestamp, never tokens. Prevent a misconfigured
      // SSR origin/cookie deployment from bouncing between these pages forever.
      const previous = Number(sessionStorage.getItem("ros-renew-attempt") ?? 0);
      if (Date.now() - previous < 15_000) {
        if (!cancelled) setError("Your session could not be restored. Please sign in again.");
        return;
      }
      try {
        await renewSession();
        if (!cancelled) {
          sessionStorage.setItem("ros-renew-attempt", String(Date.now()));
          window.location.replace(target);
        }
      } catch (failure) {
        if (cancelled) return;
        if (failure instanceof ApiError && failure.status === 401)
          window.location.replace(loginPath(target));
        else setError("We could not reach your session. Please try signing in again.");
      }
    }
    void renew();
    return () => {
      cancelled = true;
    };
  }, [next]);

  return (
    <div className="space-y-4">
      <p role={error ? "alert" : "status"}>{error || "Restoring your session…"}</p>
      {error && (
        <Link href={loginPath(next)} className="inline-block font-semibold underline">
          Go to sign in
        </Link>
      )}
    </div>
  );
}
