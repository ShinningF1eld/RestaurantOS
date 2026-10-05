"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Refresh server-derived stock after another operator changes inventory. */
export function useStockRefresh(paused = false) {
  const router = useRouter();
  useEffect(() => {
    const refresh = () => {
      if (!paused && document.visibilityState === "visible") router.refresh();
    };
    const timer = window.setInterval(refresh, 30_000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [paused, router]);
}
