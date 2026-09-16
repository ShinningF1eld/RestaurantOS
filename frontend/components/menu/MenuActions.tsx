"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { deleteMenu, updateMenu } from "@/lib/api/menu";
import type { Menu } from "@/types/menu";

export default function MenuActions({ menu, restaurantId }: { menu: Menu; restaurantId: number }) {
    const router = useRouter();
    const [editing, setEditing] = useState(false);
    const [confirmingDelete, setConfirmingDelete] = useState(false);
    const [name, setName] = useState(menu.name);
    const [description, setDescription] = useState(menu.description || "");
    const [saving, setSaving] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function save(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (!name.trim()) { setError("Menu name is required."); return; }
        setSaving(true); setError(null);
        try {
            await updateMenu(menu.menu_id, { name: name.trim(), description: description.trim() || null });
            setEditing(false);
            router.refresh();
        } catch {
            setError("Could not save menu changes. Please try again.");
        } finally { setSaving(false); }
    }

    async function remove() {
        setDeleting(true); setError(null);
        try {
            await deleteMenu(menu.menu_id);
            router.push(`/restaurants/${restaurantId}/menu`);
            router.refresh();
        } catch {
            setError("Could not delete this menu. Remove its items first if it is still in use.");
            setConfirmingDelete(false);
        } finally { setDeleting(false); }
    }

    return <>
        <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => { setEditing(true); setError(null); }} className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-stone-50">Edit menu</button>
            <button type="button" onClick={() => { setConfirmingDelete(true); setError(null); }} className="rounded-md border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 hover:bg-red-50">Delete menu</button>
        </div>
        {error ? <p role="alert" className="mt-3 text-sm text-red-700">{error}</p> : null}
        {editing ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4"><form onSubmit={save} className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"><h2 className="text-xl font-semibold">Edit menu</h2><label className="mt-5 block text-sm font-semibold text-slate-700" htmlFor="edit-menu-name">Name</label><input id="edit-menu-name" value={name} onChange={(event) => setName(event.target.value)} disabled={saving} className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2" /><label className="mt-4 block text-sm font-semibold text-slate-700" htmlFor="edit-menu-description">Description</label><textarea id="edit-menu-description" value={description} onChange={(event) => setDescription(event.target.value)} disabled={saving} rows={4} className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2" />{error ? <p role="alert" className="mt-3 text-sm text-red-700">{error}</p> : null}<div className="mt-5 flex justify-end gap-3"><button type="button" disabled={saving} onClick={() => setEditing(false)} className="rounded-md border border-slate-200 px-4 py-2 text-sm font-semibold">Cancel</button><button disabled={saving} className="rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white">{saving ? "Saving…" : "Save changes"}</button></div></form></div> : null}
        {confirmingDelete ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4"><div role="dialog" aria-modal="true" aria-labelledby="delete-menu-title" className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"><h2 id="delete-menu-title" className="text-xl font-semibold text-slate-950">Delete {menu.name}?</h2><p className="mt-2 text-sm text-slate-600">This permanently deletes the menu. It cannot be undone.</p><div className="mt-5 flex justify-end gap-3"><button type="button" disabled={deleting} onClick={() => setConfirmingDelete(false)} className="rounded-md border border-slate-200 px-4 py-2 text-sm font-semibold">Cancel</button><button type="button" disabled={deleting} onClick={remove} className="rounded-md bg-red-700 px-4 py-2 text-sm font-semibold text-white disabled:bg-red-300">{deleting ? "Deleting…" : "Delete menu"}</button></div></div></div> : null}
    </>;
}
