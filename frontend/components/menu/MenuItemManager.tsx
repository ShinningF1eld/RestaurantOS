"use client";

import { useState } from "react";

import MenuItemForm from "./MenuItemForm";

import type { MenuItem } from "@/types/menu_item";

interface MenuItemManagerProps {
    menuId: number;
}

export default function MenuItemManager({
    menuId,
}: MenuItemManagerProps) {
    const [isOpen, setIsOpen] = useState(false);
    const [editingItem, setEditingItem] =
        useState<MenuItem | undefined>();

    function openCreate() {
        setEditingItem(undefined);
        setIsOpen(true);
    }

    function handleSuccess() {
        setIsOpen(false);
        setEditingItem(undefined);

        window.location.reload();
    }

    return (
        <>
            <button
                type="button"
                onClick={openCreate}
                className="rounded-md bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800"
            >
                Add menu item
            </button>

            {isOpen && (
                <MenuItemForm
                    menuId={menuId}
                    menuItem={editingItem}
                    onClose={() => setIsOpen(false)}
                    onSuccess={handleSuccess}
                />
            )}
        </>
    );
}
