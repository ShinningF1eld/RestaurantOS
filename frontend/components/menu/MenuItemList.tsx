"use client";

import { useState } from "react";

import MenuItemForm from "./MenuItemForm";
import EmptyState from "@/components/ui/EmptyState";
import StatusBadge from "@/components/ui/StatusBadge";

import type { MenuItem } from "@/types/menu_item";

import {
    deleteMenuItem,
} from "@/lib/api/menu_item";

interface MenuItemListProps {
    menuId: number;
    menuItems: MenuItem[];
}

export default function MenuItemList({
    menuId,
    menuItems,
}: MenuItemListProps) {
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

    async function handleDelete(item: MenuItem) {
        const confirmed = window.confirm(
            `Are you sure you want to delete "${item.name}"?`
        );

        if (!confirmed) {
            return;
        }

        try {
            await deleteMenuItem(item.menu_item_id);

            window.location.reload();
        } catch (error) {
            console.error(error);

            alert("Failed to delete menu item.");
        }
    }

    return (
        <>
            <div className="flex justify-end">
                <button
                    type="button"
                    onClick={openCreate}
                    className="rounded-md bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800"
                >
                    Add menu item
                </button>
            </div>

            {menuItems.length === 0 ? (
                <div className="mt-8">
                    <EmptyState
                        title="No menu items yet"
                        description="Add the first dish, drink, modifier, or service item to start building this menu."
                        action={(
                            <button
                                type="button"
                                onClick={openCreate}
                                className="rounded-md bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800"
                            >
                                Add first item
                            </button>
                        )}
                    />
                </div>
            ) : (
                <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {menuItems.map((item) => (
                        <div
                            key={item.menu_item_id}
                            className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm transition hover:border-slate-300 hover:shadow-md"
                        >
                            <div className="flex items-start justify-between gap-4">
                                <div>
                                    <h2 className="font-semibold text-slate-950">
                                        {item.name}
                                    </h2>

                                    <p className="mt-1 text-sm leading-6 text-slate-600">
                                        {item.description ||
                                            "No description provided."}
                                    </p>
                                </div>

                                <StatusBadge tone={item.is_available ? "green" : "neutral"}>
                                    {item.is_available
                                        ? "Available"
                                        : "Unavailable"}
                                </StatusBadge>
                            </div>

                            <div className="mt-5 flex items-center justify-between border-t border-slate-200 pt-4">
                                <span className="text-lg font-semibold text-slate-950">
                                    ฿
                                    {item.price.toLocaleString()}
                                </span>

                                <div className="flex items-center">
                                    {/* Edit */}
                                    <button
                                        type="button"
                                        onClick={() => openEdit(item)}
                                        className="rounded-md px-3 py-2 text-sm font-semibold text-slate-600 transition hover:bg-stone-100 hover:text-slate-950"
                                    >
                                        Edit
                                    </button>

                                    <button
                                        type="button"
                                        onClick={() => handleDelete(item)}
                                        aria-label={`Delete ${item.name}`}
                                        className="rounded-md p-2 text-red-500 transition hover:bg-red-50 hover:text-red-600"
                                    >
                                        <svg
                                            xmlns="http://www.w3.org/2000/svg"
                                            fill="none"
                                            viewBox="0 0 24 24"
                                            strokeWidth={1.8}
                                            stroke="currentColor"
                                            className="h-5 w-5"
                                        >
                                            <path
                                                strokeLinecap="round"
                                                strokeLinejoin="round"
                                                d="M6 7h12M9 7V5h6v2m-7 0 .7 12h6.6L16 7M10 11v5m4-5v5"
                                            />
                                        </svg>
                                    </button>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

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
