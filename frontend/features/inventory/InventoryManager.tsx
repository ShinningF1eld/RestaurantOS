"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/errors";
import { inventoryApi } from "@/lib/api/inventory";
import type { Ingredient, Movement } from "@/types/inventory";

const control = "rounded-md border border-slate-300 bg-white p-2 text-sm";
const button = "rounded-md bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50";
type Editor = {
  id?: number;
  name: string;
  unit: Ingredient["unit"];
  reorder_threshold: string;
  opening_quantity: string;
  is_active: boolean;
};
const blank: Editor = {
  name: "",
  unit: "g",
  reorder_threshold: "0",
  opening_quantity: "0",
  is_active: true,
};

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
      // Keep the key after transport failures and server errors so a user retry
      // replays the same write if the server committed before its reply was lost.
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

  if (loading && items.length === 0) return <p role="status">Loading inventory…</p>;

  const activeCount = items.filter((item) => item.is_active).length;
  const lowStockCount = items.filter((item) => item.low_stock).length;

  return (
    <div className="space-y-6" aria-busy={locked}>
      {loading && <p className="sr-only" role="status">Refreshing inventory…</p>}
      {error && (
        <div role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-red-800">
          {error}{" "}
          <button className="underline" disabled={locked} onClick={() => void load()}>
            Refresh inventory
          </button>
        </div>
      )}
      {message && <p role="status">{message}</p>}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p>{activeCount} active ingredients on this page · {lowStockCount} at or below reorder threshold</p>
        {canManage && (
          <button
            className={button}
            disabled={locked || !!editor || !!selected}
            onClick={() => setEditor({ ...blank })}
          >
            Add ingredient
          </button>
        )}
      </div>

      {editor && (
        <form className="space-y-4 rounded-lg border bg-white p-5" onSubmit={saveIngredient}>
          <h2 className="font-semibold">{editor.id ? "Edit ingredient" : "Create ingredient"}</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-1">
              Ingredient name
              <input className={control} required maxLength={255} disabled={locked} value={editor.name}
                onChange={(event) => setEditor({ ...editor, name: event.target.value })} />
            </label>
            <label className="grid gap-1">
              Base unit
              <select className={control} disabled={!!editor.id || locked} value={editor.unit}
                onChange={(event) => setEditor({ ...editor, unit: event.target.value as Ingredient["unit"] })}>
                <option value="g">Grams (g)</option>
                <option value="ml">Millilitres (ml)</option>
                <option value="piece">Pieces</option>
              </select>
            </label>
            <label className="grid gap-1">
              Reorder threshold
              <input className={control} type="number" min="0" max="999999999.999" step="0.001"
                required disabled={locked} value={editor.reorder_threshold}
                onChange={(event) => setEditor({ ...editor, reorder_threshold: event.target.value })} />
            </label>
            {!editor.id && (
              <label className="grid gap-1">
                Opening stock
                <input className={control} type="number" min="0" max="999999999.999" step="0.001"
                  required disabled={locked} value={editor.opening_quantity}
                  onChange={(event) => setEditor({ ...editor, opening_quantity: event.target.value })} />
              </label>
            )}
          </div>
          <div className="flex gap-3">
            <button className={button} disabled={locked}>Save ingredient</button>
            <button type="button" disabled={locked} onClick={() => setEditor(null)}>Cancel</button>
          </div>
        </form>
      )}

      {items.length === 0 ? (
        <p className="rounded-lg border bg-white p-8">
          {ingredientOffset === 0
            ? "No ingredients yet. Add your first ingredient to start tracking stock."
            : "No ingredients on this page."}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-stone-50">
              <tr>{["Ingredient", "On hand", "Reorder threshold", "Status", "Actions"].map((label) =>
                <th className="p-3" key={label}>{label}</th>)}</tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr className="border-t" key={item.id}>
                  <td className="p-3 font-semibold">{item.name}</td>
                  <td className="p-3">{item.quantity} {item.unit}</td>
                  <td className="p-3">{item.reorder_threshold} {item.unit}</td>
                  <td className="p-3">
                    {!item.is_active ? "Archived" : item.low_stock ? "Low stock" : "Healthy"}
                  </td>
                  <td className="p-3">
                    <div className="flex flex-wrap gap-3">
                      <button disabled={locked} className="underline" onClick={() => void showHistory(item)}>
                        History for {item.name}
                      </button>
                      {canManage && (
                        <>
                          <button disabled={locked || !!selected} className="underline"
                            onClick={() => setEditor({ ...item, opening_quantity: "0" })}>
                            Edit {item.name}
                          </button>
                          {item.is_active && (
                            <button disabled={locked || !!editor || !!selected} className="underline"
                              onClick={() => {
                                setSelected(item);
                                setEditor(null);
                                setKind("receipt");
                                setAmount("");
                                setReason("");
                              }}>
                              Manage stock for {item.name}
                            </button>
                          )}
                          <button disabled={locked || !!editor || !!selected} className="underline"
                            onClick={() => void run(async () => {
                              await inventoryApi(restaurantId).update(item.id, {
                                name: item.name,
                                unit: item.unit,
                                reorder_threshold: item.reorder_threshold,
                                is_active: !item.is_active,
                              });
                              setMessage(item.is_active ? "Ingredient archived." : "Ingredient restored.");
                            })}>
                            {item.is_active ? "Archive" : "Restore"} {item.name}
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex gap-3">
        <button disabled={locked || !!selected || ingredientOffset === 0}
          onClick={() => {
            setLoading(true);
            setIngredientOffset(Math.max(0, ingredientOffset - 100));
          }}>
          Previous ingredients
        </button>
        <span>Page {ingredientOffset / 100 + 1}</span>
        <button disabled={locked || !!selected || items.length < 100}
          onClick={() => {
            setLoading(true);
            setIngredientOffset(ingredientOffset + 100);
          }}>
          Next ingredients
        </button>
      </div>

      {selected && (
        <form className="space-y-4 rounded-lg border bg-white p-5" onSubmit={saveStock}>
          <h2 className="font-semibold">Manage stock: {selected.name}</h2>
          <p>On hand: {selected.quantity} {selected.unit}. A physical count records the total quantity you counted.</p>
          <div className="grid gap-4 sm:grid-cols-3">
            <label className="grid gap-1">
              Stock action
              <select className={control} disabled={locked} value={kind}
                onChange={(event) => setKind(event.target.value)}>
                <option value="receipt">Receive stock</option>
                <option value="waste">Record waste</option>
                <option value="count">Physical count</option>
              </select>
            </label>
            <label className="grid gap-1">
              {kind === "count" ? "Counted quantity" : "Quantity"} ({selected.unit})
              <input className={control} type="number" min={kind === "count" ? "0" : "0.001"}
                max="999999999.999" step="0.001" required disabled={locked}
                value={amount} onChange={(event) => setAmount(event.target.value)} />
            </label>
            <label className="grid gap-1">
              Reason
              <input className={control} required maxLength={500} disabled={locked} value={reason}
                onChange={(event) => setReason(event.target.value)} />
            </label>
          </div>
          <div className="flex flex-wrap gap-3">
            <button className={button} disabled={locked}>Record stock</button>
            <button type="button" disabled={locked} onClick={() => setSelected(null)}>Cancel</button>
            <button type="button" disabled={locked} onClick={() => void run(async () => {
              const fresh = await inventoryApi(restaurantId).list(ingredientOffset);
              setItems(fresh);
              setSelected(fresh.find((item) => item.id === selected.id) ?? null);
              setAmount("");
              setMessage("Stock refreshed. Count again before submitting.");
            })}>
              Refresh count
            </button>
          </div>
        </form>
      )}

      {historyItem && (
        <section className="space-y-3" aria-label="Stock history">
          <h2 className="font-semibold">Stock history: {historyItem.name}</h2>
          {historyError && <p role="alert" className="text-red-800">{historyError}</p>}
          {history.length === 0 ? <p>No movements on this page.</p> : (
            <div className="overflow-x-auto rounded-lg border bg-white">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr>{["Time", "Action", "Change", "Balance", "Recorded by", "Reason"].map((label) =>
                    <th key={label} className="p-3">{label}</th>)}</tr>
                </thead>
                <tbody>
                  {history.map((row) => (
                    <tr key={row.id} className="border-t">
                      <td className="p-3">{new Date(row.occurred_at).toLocaleString()}</td>
                      <td className="p-3">{row.kind}</td>
                      <td className="p-3">{row.quantity_delta} {historyItem.unit}</td>
                      <td className="p-3">{row.balance_after} {historyItem.unit}</td>
                      <td className="p-3">{row.actor_name ?? "Former user"}</td>
                      <td className="p-3">{row.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex gap-3">
            <button disabled={locked || offset === 0}
              onClick={() => void showHistory(historyItem, Math.max(0, offset - 20))}>
              Previous history
            </button>
            <span>Page {offset / 20 + 1}</span>
            <button disabled={locked || history.length < 20}
              onClick={() => void showHistory(historyItem, offset + 20)}>
              Next history
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
