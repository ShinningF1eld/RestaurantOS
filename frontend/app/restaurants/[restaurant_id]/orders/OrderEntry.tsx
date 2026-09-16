"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { createOrder } from "@/lib/api/order";
import type { MenuItem } from "@/types/menu_item";

export default function OrderEntry({ restaurantId, items }: { restaurantId: number; items: MenuItem[] }) {
    const router = useRouter();
    const [quantities, setQuantities] = useState<Record<number, number>>({});
    const [tableNumber, setTableNumber] = useState("");
    const [customerName, setCustomerName] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const selected = useMemo(() => items.filter((item) => (quantities[item.menu_item_id] || 0) > 0), [items, quantities]);

    async function submit(event: React.FormEvent) {
        event.preventDefault();
        if (!selected.length) { setError("Choose at least one available menu item."); return; }
        setSaving(true); setError(null);
        try {
            await createOrder(restaurantId, {
                table_number: tableNumber || undefined,
                customer_name: customerName || undefined,
                items: selected.map((item) => ({ menu_item_id: item.menu_item_id, quantity: quantities[item.menu_item_id] })),
            });
            setQuantities({}); setTableNumber(""); setCustomerName(""); router.refresh();
        } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not create order."); }
        finally { setSaving(false); }
    }

    return <form onSubmit={submit} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold text-slate-950">New order</h2><p className="text-sm text-slate-600">Prices are calculated by the server when this ticket is created.</p></div><button disabled={saving || !items.length} className="rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300">{saving ? "Creating…" : "Create order"}</button></div>
        {!items.length ? <p className="mt-4 text-sm text-amber-700">There are no available menu items. Add or enable one in the menu first.</p> : <><div className="mt-4 grid gap-3 sm:grid-cols-2"><input value={tableNumber} onChange={(e) => setTableNumber(e.target.value)} placeholder="Table number (optional)" className="rounded-md border border-slate-300 px-3 py-2" /><input value={customerName} onChange={(e) => setCustomerName(e.target.value)} placeholder="Customer name (optional)" className="rounded-md border border-slate-300 px-3 py-2" /></div><div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{items.map((item) => <label key={item.menu_item_id} className="flex items-center justify-between rounded-md border border-slate-200 p-3 text-sm"><span>{item.name} <span className="text-slate-500">฿{Number(item.price).toFixed(2)}</span></span><input aria-label={`Quantity for ${item.name}`} type="number" min="0" value={quantities[item.menu_item_id] || 0} onChange={(e) => setQuantities((current) => ({ ...current, [item.menu_item_id]: Number(e.target.value) }))} className="w-16 rounded border border-slate-300 px-2 py-1" /></label>)}</div></>}
        {error ? <p role="alert" className="mt-3 text-sm text-red-700">{error}</p> : null}
    </form>;
}
