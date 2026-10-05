"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { inventoryApi } from "@/lib/api/inventory";
import { getRecipe, updateRecipe } from "@/lib/api/recipe";
import type { Ingredient } from "@/types/inventory";
import type { MenuItem } from "@/types/menu_item";

type Row = { ingredient_id: number; quantity: string };
const control = "w-full rounded-md border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-100";

export default function RecipeEditor({ item, onClose, onSaved }: {
  item: MenuItem;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [ingredients, setIngredients] = useState<Ingredient[]>([]);
  const [restaurantId, setRestaurantId] = useState<number | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [tracking, setTracking] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const recipe = await getRecipe(item.menu_item_id);
        const all: Ingredient[] = [];
        for (let offset = 0; ; offset += 100) {
          const page = await inventoryApi(recipe.restaurant_id).list(offset);
          all.push(...page);
          if (page.length < 100) break;
        }
        if (active) {
          setRestaurantId(recipe.restaurant_id);
          setIngredients(all);
          setTracking(recipe.inventory_tracking);
          setRows(recipe.components.map(({ ingredient_id, quantity }) => ({ ingredient_id, quantity })));
        }
      } catch (failure) {
        if (active) setError(failure instanceof Error ? failure.message : "Could not load this recipe.");
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [item.menu_item_id]);

  const unused = ingredients.filter((ingredient) => ingredient.is_active && !rows.some((row) => row.ingredient_id === ingredient.id));
  const busy = loading || saving;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (tracking && !rows.length) { setError("Add at least one ingredient before enabling stock tracking."); return; }
    if (new Set(rows.map((row) => row.ingredient_id)).size !== rows.length) { setError("Each ingredient can appear only once."); return; }
    if (rows.some((row) => !Number.isFinite(Number(row.quantity)) || Number(row.quantity) <= 0)) {
      setError("Enter a positive quantity for every ingredient."); return;
    }
    setSaving(true);
    try {
      await updateRecipe(item.menu_item_id, { inventory_tracking: tracking, components: rows });
      onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save this recipe.");
    } finally { setSaving(false); }
  }

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
    <section role="dialog" aria-modal="true" aria-labelledby="recipe-title" className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
      <div className="flex items-start justify-between gap-4">
        <div><h2 id="recipe-title" className="text-xl font-semibold">Recipe for {item.name}</h2><p className="mt-1 text-sm text-slate-600">Enter the ingredients used for one portion, in their inventory units.</p></div>
        <button type="button" aria-label="Close recipe" disabled={saving} onClick={onClose} className="rounded px-3 py-1 text-sm font-semibold">Close</button>
      </div>
      {loading ? <p role="status" className="mt-4">Loading recipe and ingredients…</p> : <form className="mt-5 space-y-4" onSubmit={save}>
        <label className="flex items-start gap-3 rounded-lg border border-slate-200 bg-stone-50 p-4">
          <input type="checkbox" checked={tracking} disabled={busy} onChange={(event) => setTracking(event.target.checked)} className="mt-1" />
          <span><span className="font-semibold">Track ingredient stock</span><span className="mt-1 block text-sm text-slate-600">Stock is deducted when an order is accepted. Cancelling does not return ingredients.</span></span>
        </label>
        {!ingredients.some((ingredient) => ingredient.is_active) && <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-800">No active ingredients are available. {restaurantId && <Link className="underline" href={`/restaurants/${restaurantId}/inventory`}>Create ingredients in inventory.</Link>}</p>}
        {rows.length === 0 && <p className="text-sm text-slate-600">No ingredients in this recipe yet.</p>}
        {rows.map((row, index) => {
          const ingredient = ingredients.find((entry) => entry.id === row.ingredient_id);
          return <div key={index} className="grid gap-3 rounded-lg border border-slate-200 p-3 sm:grid-cols-[1fr_9rem_auto]">
            <label className="space-y-1 text-sm">Ingredient {index + 1}<select aria-label={`Ingredient ${index + 1}`} className={control} disabled={busy} value={row.ingredient_id}
              onChange={(event) => setRows((current) => current.map((entry, position) => position === index ? { ...entry, ingredient_id: Number(event.target.value) } : entry))}>
              {ingredients.filter((entry) => entry.id === row.ingredient_id || (entry.is_active && !rows.some((other) => other.ingredient_id === entry.id))).map((entry) => <option key={entry.id} value={entry.id} disabled={!entry.is_active}>{entry.name}{entry.is_active ? "" : " (archived)"}</option>)}
            </select></label>
            <label className="space-y-1 text-sm">Quantity ({ingredient?.unit ?? ""})<input aria-label={`Recipe quantity ${index + 1}`} className={control} type="number" min="0.001" max="999999999.999" step="0.001" required disabled={busy} value={row.quantity}
              onChange={(event) => setRows((current) => current.map((entry, position) => position === index ? { ...entry, quantity: event.target.value } : entry))} /></label>
            <button type="button" aria-label={`Remove ingredient ${index + 1}`} disabled={busy} onClick={() => setRows((current) => current.filter((_, position) => position !== index))} className="self-end rounded-md px-3 py-2 text-sm font-semibold text-red-700">Remove</button>
          </div>;
        })}
        <button type="button" disabled={busy || !unused.length} onClick={() => setRows((current) => [...current, { ingredient_id: unused[0].id, quantity: "" }])} className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50">Add recipe ingredient</button>
        {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        <div className="flex justify-end gap-3 border-t border-slate-200 pt-4"><button type="button" disabled={saving} onClick={onClose} className="rounded-md border px-4 py-2 text-sm font-semibold">Cancel</button><button disabled={busy || (!!error && restaurantId === null)} className="rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300">{saving ? "Saving…" : "Save recipe"}</button></div>
      </form>}
      {loading && error && <p role="alert">{error}</p>}
    </section>
  </div>;
}
