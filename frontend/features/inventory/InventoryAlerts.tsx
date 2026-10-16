"use client";

import { useState } from "react";
import { useInventoryAlerts } from "./useInventoryAlerts";
import type { ActiveAlert, AlertHistory } from "@/types/inventory";

const button = "rounded-md border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50";
const time = (value: string) => new Date(value).toLocaleString();
const reasons = {
  stock_recovered: "Stock recovered",
  threshold_changed: "Threshold changed",
  archived: "Archived",
};

export default function InventoryAlerts({
  restaurantId,
  refreshToken,
  onAccessLost,
}: {
  restaurantId: number;
  refreshToken: number;
  onAccessLost: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const active = useInventoryAlerts<ActiveAlert>(
    restaurantId,
    false,
    true,
    refreshToken,
    onAccessLost,
  );
  const history = useInventoryAlerts<AlertHistory>(
    restaurantId,
    true,
    expanded,
    refreshToken,
    onAccessLost,
  );

  function status(resource: typeof active | typeof history, label: string) {
    return (
      <>
        {!resource.data && !resource.error && <p role="status">Loading {label}…</p>}
        {resource.error && (
          <p role="alert" className="text-red-800">
            {resource.data ? "Last-known data — refresh failed. " : "Could not load data. "}
            {resource.error}{" "}
            <button className={button} onClick={() => void resource.refresh()}>
              Retry {label}
            </button>
          </p>
        )}
        {resource.updatedAt && (
          <p className="text-xs text-slate-500">
            {resource.error ? "Stale. " : ""}Last refreshed{" "}
            {resource.updatedAt.toLocaleTimeString()}. Episode updates may be delayed while
            processing catches up.
          </p>
        )}
      </>
    );
  }

  function pagination(resource: typeof active | typeof history, label: string) {
    if (!resource.data) return null;
    return (
      <div className="flex items-center gap-3">
        <button
          className={button}
          disabled={resource.offset === 0 || resource.refreshing}
          onClick={() => resource.changePage(Math.max(0, resource.offset - 20))}
        >
          Previous {label}
        </button>
        <span className="text-sm">
          Page {resource.offset / 20 + 1} · {resource.data.total} episodes
        </span>
        <button
          className={button}
          disabled={resource.offset + 20 >= resource.data.total || resource.refreshing}
          onClick={() => resource.changePage(resource.offset + 20)}
        >
          Next {label}
        </button>
      </div>
    );
  }

  return (
    <section
      aria-label="Inventory alerts"
      aria-busy={active.refreshing || (expanded && history.refreshing)}
      className="space-y-4 rounded-xl border border-amber-200 bg-white p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold">Active alerts</h2>
        <button
          className={button}
          disabled={active.refreshing || (expanded && history.refreshing)}
          onClick={() => {
            void active.refresh();
            if (expanded) void history.refresh();
          }}
        >
          Refresh alerts
        </button>
      </div>
      {status(active, "alerts")}
      {active.data && (
        <>
          {active.data.items.length === 0 && !active.error && (
            <p>
              No active alerts on this page. Live low-stock indicators below remain available while
              processing catches up.
            </p>
          )}
          <ul className="space-y-2">
            {active.data.items.map((row) => (
              <li key={row.episode_id} className="rounded-lg bg-amber-50 p-3">
                <strong>{row.ingredient_name}</strong>: {row.quantity} {row.unit} · Threshold{" "}
                {row.reorder_threshold} {row.unit}
                <p className="text-sm">
                  {row.notification_suppressed ? "Low when tracking started" : "Low since"}{" "}
                  {time(row.opened_at)}
                </p>
              </li>
            ))}
          </ul>
          {pagination(active, "alerts")}
        </>
      )}
      <button
        className={button}
        aria-expanded={expanded}
        aria-controls="alert-history"
        onClick={() => setExpanded(!expanded)}
      >
        Alert history
      </button>
      {expanded && (
        <div id="alert-history" className="space-y-3">
          {status(history, "alert history")}
          {history.data && (
            <>
              {history.data.items.length === 0 && !history.error && (
                <p>No alert episodes on this page.</p>
              )}
              <ul className="space-y-2">
                {history.data.items.map((row) => (
                  <li key={row.episode_id} className="rounded-lg border border-slate-200 p-3">
                    <strong>{row.ingredient_name}</strong> · Opening {row.opening_quantity}{" "}
                    {row.unit} · Threshold {row.opening_threshold} {row.unit}
                    <p className="text-sm">
                      {row.opening_source === "maintenance_initialization"
                        ? "Low when tracking started"
                        : "Opened"}{" "}
                      {time(row.opened_at)}
                    </p>
                    <p className="text-sm">
                      {row.resolved_at
                        ? `Resolved ${time(row.resolved_at)} · ${row.resolution_reason ? reasons[row.resolution_reason] : "Resolved"}`
                        : "Active in recorded history"}
                    </p>
                  </li>
                ))}
              </ul>
              {pagination(history, "alert history")}
            </>
          )}
        </div>
      )}
    </section>
  );
}
