"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/errors";
import { inventoryApi } from "@/lib/api/inventory";
import type { ActiveAlert, AlertHistory, AlertPage } from "@/types/inventory";

/** Each page owns its request generation; obsolete responses cannot restore old scope/data. */
export function useInventoryAlerts<T extends ActiveAlert | AlertHistory>(
  restaurantId: number,
  history: boolean,
  enabled: boolean,
  refreshToken: number,
  onAccessLost: () => void,
) {
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<AlertPage<T> | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    const request = ++generation.current;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setRefreshing(true);
    try {
      const api = inventoryApi(restaurantId);
      const page = await (history
        ? api.alertHistory(offset, current.signal)
        : api.alerts(offset, current.signal));
      if (request !== generation.current) return;
      setData(page as AlertPage<T>);
      setError("");
      setUpdatedAt(new Date());
    } catch (failure) {
      if (request !== generation.current || current.signal.aborted) return;
      if (failure instanceof ApiError && [401, 403, 404].includes(failure.status)) {
        setData(null);
        onAccessLost();
      } else {
        setError(failure instanceof Error ? failure.message : "Could not load alerts.");
      }
    } finally {
      if (request === generation.current) setRefreshing(false);
    }
  }, [restaurantId, history, offset, onAccessLost]);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (active) void refresh();
    });
    const visibleRefresh = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    const timer = window.setInterval(visibleRefresh, 15_000);
    document.addEventListener("visibilitychange", visibleRefresh);
    const invalidate = () => {
      ++generation.current;
      controller.current?.abort();
    };
    return () => {
      active = false;
      invalidate();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visibleRefresh);
    };
  }, [enabled, refresh, refreshToken]);

  function changePage(next: number) {
    ++generation.current;
    controller.current?.abort();
    setData(null);
    setError("");
    setUpdatedAt(null);
    setOffset(next);
  }

  return { data, error, refreshing, updatedAt, offset, changePage, refresh };
}
