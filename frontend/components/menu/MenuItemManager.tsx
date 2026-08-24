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

    function openEdit(item: MenuItem) {
        setEditingItem(item);
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
                className="rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-gray-800 cursor-pointer"
            >
                + Add Menu Item
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