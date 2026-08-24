"use client";

import { useState } from "react";

import MenuItemForm from "./MenuItemForm";

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
            {/* Add button */}
            <div className="flex justify-end">
                <button
                    type="button"
                    onClick={openCreate}
                    className="rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-gray-800 cursor-pointer"
                >
                    + Add Menu Item
                </button>
            </div>

            {/* Menu items */}
            {menuItems.length === 0 ? (
                <div className="mt-8 rounded-xl border border-dashed bg-white p-12 text-center">
                    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-gray-100 text-xl">
                        🍽️
                    </div>

                    <h2 className="mt-4 text-lg font-semibold">
                        No menu items yet
                    </h2>

                    <p className="mx-auto mt-2 max-w-sm text-sm text-gray-500">
                        Add your first menu item to start building
                        this menu.
                    </p>

                    <button
                        type="button"
                        onClick={openCreate}
                        className="mt-6 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-gray-800"
                    >
                        Add your first item
                    </button>
                </div>
            ) : (
                <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {menuItems.map((item) => (
                        <div
                            key={item.menu_item_id}
                            className="rounded-xl border bg-white p-5 shadow-sm transition hover:shadow-md"
                        >
                            <div className="flex items-start justify-between gap-4">
                                <div>
                                    <h2 className="font-semibold text-gray-900">
                                        {item.name}
                                    </h2>

                                    <p className="mt-1 text-sm text-gray-500">
                                        {item.description ||
                                            "No description provided."}
                                    </p>
                                </div>

                                <span
                                    className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${item.is_available
                                        ? "bg-green-50 text-green-700"
                                        : "bg-gray-100 text-gray-500"
                                        }`}
                                >
                                    {item.is_available
                                        ? "Available"
                                        : "Unavailable"}
                                </span>
                            </div>

                            <div className="mt-5 flex items-center justify-between border-t pt-4">
                                <span className="text-lg font-bold text-gray-900">
                                    ฿
                                    {item.price.toLocaleString()}
                                </span>

                                <div className="flex items-center">
                                    {/* Edit */}
                                    <button
                                        type="button"
                                        onClick={() => openEdit(item)}
                                        className="rounded-lg px-3 py-2 text-sm font-medium text-gray-600 transition hover:bg-gray-100 hover:text-gray-900 cursor-pointer"
                                    >
                                        Edit
                                    </button>

                                    {/* Delete */}
                                    <button
                                        type="button"
                                        onClick={() => handleDelete(item)}
                                        aria-label={`Delete ${item.name}`}
                                        className="rounded-lg p-2 text-red-500 transition hover:bg-red-50 hover:text-red-600 cursor-pointer"
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

            {/* Create / Edit modal */}
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