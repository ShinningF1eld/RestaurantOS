"use client";

import { Fragment, type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import StatCard from "@/components/ui/StatCard";
import StatusBadge from "@/components/ui/StatusBadge";
import { ApiError } from "@/lib/api/errors";
import { inventoryApi } from "@/lib/api/inventory";
import type { Ingredient, Movement } from "@/types/inventory";

const control = "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100";
const primaryButton = "inline-flex min-h-10 cursor-pointer items-center justify-center rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300";
const secondaryButton = "inline-flex min-h-9 cursor-pointer items-center justify-center rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-stone-50 hover:text-slate-950 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-500 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400";
const closeButton = "inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-semibold text-slate-600 transition hover:bg-stone-100 hover:text-slate-950 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-500 disabled:cursor-not-allowed disabled:text-slate-400";
const rowActionBase = "inline-flex min-h-9 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md border px-2.5 py-1.5 text-xs font-semibold shadow-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50";
const rowActionDefault = "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-stone-50 hover:text-slate-950 focus-visible:outline-slate-500";
const rowActionSelected = "border-slate-400 bg-slate-100 text-slate-950 ring-1 ring-slate-200 focus-visible:outline-slate-700";
const rowActionDanger = "border-red-200 bg-white text-red-700 hover:border-red-300 hover:bg-red-50 focus-visible:outline-red-600";
const rowActionRestore = "border-emerald-200 bg-white text-emerald-800 hover:border-emerald-300 hover:bg-emerald-50 focus-visible:outline-emerald-600";

type Editor = {
  id?: number;
  name: string;
  unit: Ingredient["unit"];
  reorder_threshold: string;
  opening_quantity: string;
  is_active: boolean;
};

type ActionIconName = "history" | "edit" | "stock" | "archive" | "restore" | "close";

const blank: Editor = {
  name: "",
  unit: "g",
  reorder_threshold: "0",
  opening_quantity: "0",
  is_active: true,
};

function ActionIcon({ name }: { name: ActionIconName }) {
  const paths: Record<ActionIconName, string> = {
    history: "M3 12a9 9 0 1 0 2.64-6.36L3 8m0-4v4h4m5-2v6l4 2",
    edit: "m15.232 5.232 3.536 3.536M4 20l4.5-1 10.732-10.732a2.5 2.5 0 0 0-3.536-3.536L4.964 15.464 4 20Z",
    stock: "M4 7.5 12 3l8 4.5v9L12 21l-8-4.5v-9ZM4 7.5l8 4.5m0 9v-9m8-4.5-8 4.5m-4-7 8 4.5",
    archive: "M3 7h18v13H3V7Zm-1-4h20v4H2V3Zm7 8h6",
    restore: "M4 4v5h5M4.5 9A8 8 0 1 1 5 16",
    close: "m6 6 12 12M18 6 6 18",
  };

  return (
    <svg
      aria-hidden="true"
      className="h-4 w-4 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
      viewBox="0 0 24 24"
    >
      <path d={paths[name]} />
    </svg>
  );
}

function RowAction({
  accessibleName,
  children,
  disabled,
  expanded,
  controls,
  icon,
  onClick,
  tone = "default",
}: {
  accessibleName: string;
  children: string;
  disabled?: boolean;
  expanded?: boolean;
  controls?: string;
  icon: ActionIconName;
  onClick: () => void;
  tone?: "default" | "danger" | "restore";
}) {
  const color = expanded
    ? rowActionSelected
    : tone === "danger"
      ? rowActionDanger
      : tone === "restore"
        ? rowActionRestore
        : rowActionDefault;

  return (
    <button
      aria-label={accessibleName}
      aria-controls={expanded ? controls : undefined}
      aria-expanded={expanded}
      className={`${rowActionBase} ${color}`}
      disabled={disabled}
      onClick={onClick}
      title={accessibleName}
      type="button"
    >
      <ActionIcon name={icon} />
      <span>{children}</span>
    </button>
  );
}

function errorMessage(failure: unknown, fallback: string) {
  return failure instanceof Error ? failure.message : fallback;
}

export default function InventoryManager({
  restaurantId,
  canManage,
}: {
  restaurantId: number;
  canManage: boolean;
}) {
  const [items, setItems] = useState<Ingredient[]>([]);
  const [ingredientOffset, setIngredientOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editor, setEditor] = useState<Editor | null>(null);
  const [selected, setSelected] = useState<Ingredient | null>(null);
  const [kind, setKind] = useState("receipt");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [historyItem, setHistoryItem] = useState<Ingredient | null>(null);
  const [history, setHistory] = useState<Movement[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [offset, setOffset] = useState(0);
  const pending = useRef<{ signature: string; key: string } | null>(null);
  const locked = busy || loading;

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      setItems(await inventoryApi(restaurantId).list(ingredientOffset));
      setError("");
    } catch (failure) {
      setError(errorMessage(failure, "Could not load inventory."));
    } finally {
      setLoading(false);
    }
  }, [restaurantId, ingredientOffset]);

  useEffect(() => {
    let active = true;
    void inventoryApi(restaurantId).list(ingredientOffset)
      .then((rows) => {
        if (active) {
          setItems(rows);
          setError("");
        }
      })
      .catch((failure: unknown) => {
        if (active) setError(errorMessage(failure, "Could not load inventory."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [restaurantId, ingredientOffset]);

  function keyFor(payload: object) {
    const signature = JSON.stringify(payload);
    if (!pending.current || pending.current.signature !== signature) {
      pending.current = { signature, key: crypto.randomUUID() };
    }
    return pending.current.key;
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      pending.current = null;
      await load();
    } catch (failure) {
      setError(errorMessage(failure, "Could not save inventory."));
      // Retain the key after uncertain server failures so retrying cannot
      // record a second movement if the first response was lost.
      if (failure instanceof ApiError && failure.status < 500) pending.current = null;
    } finally {
      setBusy(false);
    }
  }

  async function saveIngredient(event: FormEvent) {
    event.preventDefault();
    if (!editor) return;
    await run(async () => {
      const fields = {
        name: editor.name,
        unit: editor.unit,
        reorder_threshold: editor.reorder_threshold,
      };
      if (editor.id) {
        await inventoryApi(restaurantId).update(editor.id, {
          ...fields,
          is_active: editor.is_active,
        });
      } else {
        const payload = { ...fields, opening_quantity: editor.opening_quantity };
        await inventoryApi(restaurantId).create({
          ...payload,
          idempotency_key: keyFor({ operation: "create", ...payload }),
        });
      }
      setEditor(null);
      setMessage("Ingredient saved.");
    });
  }

  async function saveStock(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    await run(async () => {
      const payload = {
        kind,
        quantity: amount,
        reason,
        expected_version: kind === "count" ? selected.version : null,
      };
      await inventoryApi(restaurantId).stock(selected.id, {
        ...payload,
        idempotency_key: keyFor({ ingredient_id: selected.id, ...payload }),
      });
      setSelected(null);
      setAmount("");
      setReason("");
      setMessage("Stock recorded.");
      if (historyItem?.id === selected.id) {
        try {
          const freshHistory = await inventoryApi(restaurantId).history(selected.id);
          setHistory(freshHistory);
          setOffset(0);
          setHistoryError("");
        } catch {
          setHistoryError("Stock saved, but history could not refresh. Reopen history to retry.");
        }
      }
    });
  }

  async function showHistory(item: Ingredient, next = 0) {
    setBusy(true);
    setError("");
    setHistoryError("");
    if (historyItem?.id !== item.id) {
      setHistory([]);
      setOffset(0);
    }
    setHistoryItem(item);
    try {
      setHistory(await inventoryApi(restaurantId).history(item.id, next));
      setOffset(next);
    } catch (failure) {
      setHistoryError(errorMessage(failure, "Could not load history."));
    } finally {
      setBusy(false);
    }
  }

  function closeHistory() {
    setHistoryItem(null);
    setHistory([]);
    setHistoryError("");
    setOffset(0);
  }

  function openHistory(item: Ingredient) {
    if (historyItem?.id === item.id) {
      closeHistory();
      return;
    }
    if (editor && editor.id !== item.id) setEditor(null);
    if (selected && selected.id !== item.id) {
      setSelected(null);
      setAmount("");
      setReason("");
    }
    void showHistory(item);
  }

  function openEditor(item: Ingredient) {
    if (editor?.id === item.id) {
      setEditor(null);
      return;
    }
    setSelected(null);
    setAmount("");
    setReason("");
    if (historyItem && historyItem.id !== item.id) closeHistory();
    setEditor({ ...item, opening_quantity: "0" });
  }

  function openStock(item: Ingredient) {
    if (selected?.id === item.id) {
      setSelected(null);
      setAmount("");
      setReason("");
      return;
    }
    setEditor(null);
    if (historyItem && historyItem.id !== item.id) closeHistory();
    setSelected(item);
    setKind("receipt");
    setAmount("");
    setReason("");
  }

  function changeIngredientPage(nextOffset: number) {
    closeHistory();
    setLoading(true);
    setIngredientOffset(nextOffset);
  }

  if (loading && items.length === 0) return <p role="status">Loading inventory…</p>;

  const activeCount = items.filter((item) => item.is_active).length;
  const lowStockCount = items.filter((item) => item.low_stock).length;

  return (
    <div className="space-y-6" aria-busy={locked}>
      {loading && <p className="sr-only" role="status">Refreshing inventory…</p>}
      {error && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-red-800">
          {error}{" "}
          <button className="cursor-pointer underline disabled:cursor-not-allowed" disabled={locked} onClick={() => void load()}>
            Refresh inventory
          </button>
        </div>
      )}
      {message && <p role="status">{message}</p>}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="text-sm text-slate-600">Balances use each ingredient’s fixed base unit.</p>
        {canManage && (
          <button
            className={primaryButton}
            disabled={locked || !!editor || !!selected}
            onClick={() => setEditor({ ...blank })}
            type="button"
          >
            Add ingredient
          </button>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <StatCard
          label="Active ingredients"
          value={activeCount}
          detail="On this page"
          tone="blue"
        />
        <StatCard
          label="Low stock"
          value={lowStockCount}
          detail="At or below reorder threshold"
          tone={lowStockCount > 0 ? "amber" : "green"}
        />
      </div>

      {editor && !editor.id && (
        <form className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5" onSubmit={saveIngredient}>
          <div>
            <h2 className="font-semibold text-slate-950">Create ingredient</h2>
            <p className="mt-1 text-sm text-slate-600">Set the base unit and starting stock for this restaurant.</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm font-medium text-slate-700">
              Ingredient name
              <input className={control} required maxLength={255} disabled={locked} value={editor.name}
                onChange={(event) => setEditor({ ...editor, name: event.target.value })} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-slate-700">
              Base unit
              <select className={control} disabled={locked} value={editor.unit}
                onChange={(event) => setEditor({ ...editor, unit: event.target.value as Ingredient["unit"] })}>
                <option value="g">Grams (g)</option>
                <option value="ml">Millilitres (ml)</option>
                <option value="piece">Pieces</option>
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-slate-700">
              Reorder threshold
              <input className={control} type="number" min="0" max="999999999.999" step="0.001"
                required disabled={locked} value={editor.reorder_threshold}
                onChange={(event) => setEditor({ ...editor, reorder_threshold: event.target.value })} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-slate-700">
              Opening stock
              <input className={control} type="number" min="0" max="999999999.999" step="0.001"
                required disabled={locked} value={editor.opening_quantity}
                onChange={(event) => setEditor({ ...editor, opening_quantity: event.target.value })} />
            </label>
          </div>
          <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
            <button className={primaryButton} disabled={locked}>Save ingredient</button>
            <button className={secondaryButton} type="button" disabled={locked} onClick={() => setEditor(null)}>Cancel</button>
          </div>
        </form>
      )}

      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center sm:p-12">
          <h2 className="font-semibold text-slate-950">
            {ingredientOffset === 0 ? "No ingredients yet" : "No ingredients on this page"}
          </h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-600">
            {ingredientOffset === 0
              ? "Add ingredients to record starting stock, deliveries, waste, and physical counts."
              : "Try the previous page to find more ingredients."}
          </p>
          {canManage && ingredientOffset === 0 && !editor && (
            <button className={`${primaryButton} mt-5`} disabled={locked} onClick={() => setEditor({ ...blank })} type="button">
              Add first ingredient
            </button>
          )}
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Ingredient stock and available actions</caption>
            <thead className="hidden bg-stone-50 text-xs font-semibold uppercase tracking-wide text-slate-500 sm:table-header-group">
              <tr>
                <th className="px-4 py-3">Ingredient</th>
                <th className="px-4 py-3">On hand</th>
                <th className="px-4 py-3">Reorder threshold</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="block divide-y divide-slate-100 sm:table-row-group">
              {items.map((item) => {
                const detailId = `inventory-details-${item.id}`;
                const historyOpen = historyItem?.id === item.id;
                const editOpen = editor?.id === item.id;
                const stockOpen = selected?.id === item.id;
                const detailOpen = historyOpen || editOpen || stockOpen;
                const editDisabled = locked || !!selected || (!!editor && editor.id !== item.id);
                const stockDisabled = locked || !!editor || (!!selected && selected.id !== item.id);
                const historyDisabled = locked || (!!editor && (editor.id === undefined || editor.id !== item.id))
                  || (!!selected && selected.id !== item.id);
                const archiveDisabled = locked || !!editor || !!selected;

                return (
                  <Fragment key={item.id}>
                    <tr
                      className="block px-3 py-2 transition-colors hover:bg-stone-50/70 sm:table-row sm:px-0 sm:py-0"
                      data-testid={`ingredient-row-${item.id}`}
                    >
                      <td className="block px-0 py-2 sm:table-cell sm:px-4 sm:py-3.5">
                        <div className="font-semibold text-slate-950">{item.name}</div>
                        <div className="mt-0.5 text-xs text-slate-500">Base unit: {item.unit}</div>
                      </td>
                      <td className="grid grid-cols-[7.25rem_minmax(0,1fr)] items-baseline gap-2 px-0 py-1.5 text-slate-800 sm:table-cell sm:px-4 sm:py-3.5">
                        <span className="text-xs font-medium text-slate-500 sm:hidden">On hand</span>
                        <span className="font-medium tabular-nums">{item.quantity} <span className="text-slate-500">{item.unit}</span></span>
                      </td>
                      <td className="grid grid-cols-[7.25rem_minmax(0,1fr)] items-baseline gap-2 px-0 py-1.5 text-slate-700 sm:table-cell sm:px-4 sm:py-3.5">
                        <span className="text-xs font-medium text-slate-500 sm:hidden">Reorder</span>
                        <span className="tabular-nums">{item.reorder_threshold} <span className="text-slate-500">{item.unit}</span></span>
                      </td>
                      <td className="grid grid-cols-[7.25rem_minmax(0,1fr)] items-center gap-2 px-0 py-1.5 sm:table-cell sm:px-4 sm:py-3.5">
                        <span className="text-xs font-medium text-slate-500 sm:hidden">Status</span>
                        <StatusBadge tone={!item.is_active ? "neutral" : item.low_stock ? "amber" : "green"}>
                          {!item.is_active ? "Archived" : item.low_stock ? "Low stock" : "Healthy"}
                        </StatusBadge>
                      </td>
                      <td className="block px-0 py-2 sm:table-cell sm:px-4 sm:py-3">
                        <div className="grid gap-2 sm:block">
                          <span className="text-xs font-medium text-slate-500 sm:hidden">Actions</span>
                          <div className="flex flex-wrap gap-1.5">
                          <RowAction
                            accessibleName={`History for ${item.name}`}
                            controls={detailId}
                            disabled={historyDisabled}
                            expanded={historyOpen}
                            icon="history"
                            onClick={() => openHistory(item)}
                          >
                            History
                          </RowAction>
                          {canManage && (
                            <>
                              <RowAction
                                accessibleName={`Edit ${item.name}`}
                                controls={detailId}
                                disabled={editDisabled}
                                expanded={editOpen}
                                icon="edit"
                                onClick={() => openEditor(item)}
                              >
                                Edit
                              </RowAction>
                              {item.is_active && (
                                <RowAction
                                  accessibleName={`Manage stock for ${item.name}`}
                                  controls={detailId}
                                  disabled={stockDisabled}
                                  expanded={stockOpen}
                                  icon="stock"
                                  onClick={() => openStock(item)}
                                >
                                  Stock
                                </RowAction>
                              )}
                              <RowAction
                                accessibleName={`${item.is_active ? "Archive" : "Restore"} ${item.name}`}
                                disabled={archiveDisabled}
                                icon={item.is_active ? "archive" : "restore"}
                                onClick={() => void run(async () => {
                                  await inventoryApi(restaurantId).update(item.id, {
                                    name: item.name,
                                    unit: item.unit,
                                    reorder_threshold: item.reorder_threshold,
                                    is_active: !item.is_active,
                                  });
                                  setMessage(item.is_active ? "Ingredient archived." : "Ingredient restored.");
                                })}
                                tone={item.is_active ? "danger" : "restore"}
                              >
                                {item.is_active ? "Archive" : "Restore"}
                              </RowAction>
                            </>
                          )}
                          </div>
                        </div>
                      </td>
                    </tr>
                    {detailOpen && (
                      <tr
                        className="block border-t border-slate-200 bg-stone-50/70 sm:table-row"
                        data-testid={`ingredient-details-${item.id}`}
                        id={detailId}
                      >
                        <td className="block p-3 sm:table-cell sm:p-5" colSpan={5}>
                          <div className="space-y-4">
                            {editOpen && editor && (
                              <form
                                aria-label={`Edit ingredient ${item.name}`}
                                className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"
                                onSubmit={saveIngredient}
                              >
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                  <div>
                                    <h2 className="font-semibold text-slate-950">Edit ingredient</h2>
                                    <p className="mt-1 text-sm text-slate-600">Update the name or reorder threshold. Base unit is fixed.</p>
                                  </div>
                                  <button
                                    aria-label={`Close edit for ${item.name}`}
                                    className={closeButton}
                                    disabled={locked}
                                    onClick={() => setEditor(null)}
                                    type="button"
                                  >
                                    <ActionIcon name="close" />
                                    Close
                                  </button>
                                </div>
                                <div className="grid gap-4 sm:grid-cols-2">
                                  <label className="grid gap-1.5 text-sm font-medium text-slate-700">
                                    Ingredient name
                                    <input className={control} required maxLength={255} disabled={locked} value={editor.name}
                                      onChange={(event) => setEditor({ ...editor, name: event.target.value })} />
                                  </label>
                                  <label className="grid gap-1.5 text-sm font-medium text-slate-700">
                                    Base unit
                                    <select className={control} disabled value={editor.unit}
                                      onChange={(event) => setEditor({ ...editor, unit: event.target.value as Ingredient["unit"] })}>
                                      <option value="g">Grams (g)</option>
                                      <option value="ml">Millilitres (ml)</option>
                                      <option value="piece">Pieces</option>
                                    </select>
                                  </label>
                                  <label className="grid gap-1.5 text-sm font-medium text-slate-700">
                                    Reorder threshold
                                    <input className={control} type="number" min="0" max="999999999.999" step="0.001"
                                      required disabled={locked} value={editor.reorder_threshold}
                                      onChange={(event) => setEditor({ ...editor, reorder_threshold: event.target.value })} />
                                  </label>
                                </div>
                                <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
                                  <button className={primaryButton} disabled={locked}>Save ingredient</button>
                                  <button className={secondaryButton} type="button" disabled={locked} onClick={() => setEditor(null)}>Cancel</button>
                                </div>
                              </form>
                            )}

                            {stockOpen && selected && (
                              <form
                                aria-label={`Manage stock form for ${item.name}`}
                                className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"
                                onSubmit={saveStock}
                              >
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                  <div>
                                    <h2 className="font-semibold text-slate-950">Manage stock: {selected.name}</h2>
                                    <p className="mt-1 text-sm text-slate-600">
                                      On hand: <span className="font-semibold tabular-nums">{selected.quantity} {selected.unit}</span>.
                                      {" "}A physical count records the total quantity you counted.
                                    </p>
                                  </div>
                                  <button
                                    aria-label={`Close stock form for ${selected.name}`}
                                    className={closeButton}
                                    disabled={locked}
                                    onClick={() => openStock(selected)}
                                    type="button"
                                  >
                                    <ActionIcon name="close" />
                                    Close
                                  </button>
                                </div>
                                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                                  <label className="grid gap-1.5 text-sm font-medium text-slate-700">
                                    Stock action
                                    <select className={control} disabled={locked} value={kind}
                                      onChange={(event) => setKind(event.target.value)}>
                                      <option value="receipt">Receive stock</option>
                                      <option value="waste">Record waste</option>
                                      <option value="count">Physical count</option>
                                    </select>
                                  </label>
                                  <label className="grid gap-1.5 text-sm font-medium text-slate-700">
                                    {kind === "count" ? "Counted quantity" : "Quantity"} ({selected.unit})
                                    <input className={control} type="number" min={kind === "count" ? "0" : "0.001"}
                                      max="999999999.999" step="0.001" required disabled={locked}
                                      value={amount} onChange={(event) => setAmount(event.target.value)} />
                                  </label>
                                  <label className="grid gap-1.5 text-sm font-medium text-slate-700">
                                    Reason
                                    <input className={control} required maxLength={500} disabled={locked} value={reason}
                                      onChange={(event) => setReason(event.target.value)} />
                                  </label>
                                </div>
                                <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
                                  <button className={primaryButton} disabled={locked}>Record stock</button>
                                  <button className={secondaryButton} type="button" disabled={locked} onClick={() => openStock(selected)}>Cancel</button>
                                  <button className={secondaryButton} type="button" disabled={locked} onClick={() => void run(async () => {
                                    const fresh = await inventoryApi(restaurantId).list(ingredientOffset);
                                    setItems(fresh);
                                    setSelected(fresh.find((entry) => entry.id === selected.id) ?? null);
                                    setAmount("");
                                    setMessage("Stock refreshed. Count again before submitting.");
                                  })}>
                                    Refresh count
                                  </button>
                                </div>
                              </form>
                            )}

                            {historyOpen && historyItem && (
                              <section aria-label="Stock history" className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                  <div>
                                    <h2 className="font-semibold text-slate-950">Stock history: {historyItem.name}</h2>
                                    <p className="mt-1 text-sm text-slate-600">Newest stock movements first.</p>
                                  </div>
                                  <button
                                    aria-label={`Close history for ${item.name}`}
                                    className={closeButton}
                                    disabled={locked}
                                    onClick={closeHistory}
                                    type="button"
                                  >
                                    <ActionIcon name="close" />
                                    Close
                                  </button>
                                </div>
                                {historyError && <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{historyError}</p>}
                                {history.length === 0 ? <p className="rounded-md bg-stone-50 px-3 py-4 text-sm text-slate-600">No movements on this page.</p> : (
                                  <ul className="max-h-[28rem] space-y-2 overflow-y-auto">
                                    {history.map((row) => (
                                      <li key={row.id} className="rounded-lg border border-slate-200 bg-white p-3 sm:p-4">
                                        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                                          <span className="font-semibold capitalize text-slate-950">{row.kind}</span>
                                          <time className="text-xs text-slate-500" dateTime={row.occurred_at}>
                                            {new Date(row.occurred_at).toLocaleString()}
                                          </time>
                                        </div>
                                        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
                                          <div>
                                            <dt className="text-xs font-medium text-slate-500">Change</dt>
                                            <dd className="mt-0.5 tabular-nums text-slate-800">{row.quantity_delta} {historyItem.unit}</dd>
                                          </div>
                                          <div>
                                            <dt className="text-xs font-medium text-slate-500">Balance</dt>
                                            <dd className="mt-0.5 tabular-nums text-slate-800">{row.balance_after} {historyItem.unit}</dd>
                                          </div>
                                          <div className="col-span-2 sm:col-span-1">
                                            <dt className="text-xs font-medium text-slate-500">Recorded by</dt>
                                            <dd className="mt-0.5 break-words text-slate-800">{row.actor_name ?? "Former user"}</dd>
                                          </div>
                                          <div className="col-span-2 sm:col-span-1">
                                            <dt className="text-xs font-medium text-slate-500">Reason</dt>
                                            <dd className="mt-0.5 break-words text-slate-800">{row.reason}</dd>
                                          </div>
                                        </dl>
                                      </li>
                                    ))}
                                  </ul>
                                )}
                                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
                                  <span className="text-sm text-slate-600">Page {offset / 20 + 1}</span>
                                  <div className="flex gap-2">
                                    <button className={secondaryButton} disabled={locked || offset === 0}
                                      onClick={() => void showHistory(historyItem, Math.max(0, offset - 20))}>
                                      Previous history
                                    </button>
                                    <button className={secondaryButton} disabled={locked || history.length < 20}
                                      onClick={() => void showHistory(historyItem, offset + 20)}>
                                      Next history
                                    </button>
                                  </div>
                                </div>
                              </section>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4">
        <span className="text-sm text-slate-600">Page {ingredientOffset / 100 + 1}</span>
        <div className="flex gap-2">
          <button className={secondaryButton} disabled={locked || !!selected || !!editor || ingredientOffset === 0}
            onClick={() => changeIngredientPage(Math.max(0, ingredientOffset - 100))}>
            Previous ingredients
          </button>
          <button className={secondaryButton} disabled={locked || !!selected || !!editor || items.length < 100}
            onClick={() => changeIngredientPage(ingredientOffset + 100)}>
            Next ingredients
          </button>
        </div>
      </div>
    </div>
  );
}
