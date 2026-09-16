"use client";

import { FormEvent, useState } from "react";

import {
    createMenuItem,
    updateMenuItem,
} from "@/lib/api/menu_item";

import type {
    MenuItem,
    MenuItemCreate,
    MenuItemUpdate,
} from "@/types/menu_item";

interface MenuItemFormProps {
    menuId: number;
    menuItem?: MenuItem;
    onClose: () => void;
    onSuccess: () => void;
}

export default function MenuItemForm({
    menuId,
    menuItem,
    onClose,
    onSuccess,
}: MenuItemFormProps) {
    const isEditing = !!menuItem;

    const [name, setName] = useState(menuItem?.name ?? "");
    const [description, setDescription] = useState(
        menuItem?.description ?? ""
    );
    const [price, setPrice] = useState(
        menuItem?.price?.toString() ?? ""
    );
    const [isAvailable, setIsAvailable] = useState(
        menuItem?.is_available ?? true
    );

    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");

    async function handleSubmit(
        event: FormEvent<HTMLFormElement>
    ) {
        event.preventDefault();

        if (!name.trim()) {
            setError("Menu item name is required.");
            return;
        }

        const numericPrice = Number(price);

        if (!price || Number.isNaN(numericPrice) || numericPrice < 0) {
            setError("Please enter a valid price.");
            return;
        }

        try {
            setLoading(true);
            setError("");

            if (isEditing && menuItem) {
                const data: MenuItemUpdate = {
                    name: name.trim(),
                    description: description.trim() || null,
                    price: numericPrice,
                    is_available: isAvailable,
                };

                await updateMenuItem(
                    menuItem.menu_item_id,
                    data
                );
            } else {
                const data: MenuItemCreate = {
                    name: name.trim(),
                    description: description.trim() || null,
                    price: numericPrice,
                    is_available: isAvailable,
                };

                await createMenuItem(menuId, data);
            }

            onSuccess();
        } catch (error) {
            console.error(error);

            setError(
                isEditing
                    ? "Failed to update menu item."
                    : "Failed to create menu item."
            );
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
            <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-xl">
                <div className="flex items-start justify-between">
                    <div>
                        <h2 className="text-xl font-semibold text-slate-950">
                            {isEditing
                                ? "Edit Menu Item"
                                : "Add Menu Item"}
                        </h2>

                        <p className="mt-1 text-sm text-slate-600">
                            {isEditing
                                ? "Update this menu item's information."
                                : "Add a new item to this menu."}
                        </p>
                    </div>

                    <button
                        type="button"
                        onClick={onClose}
                        disabled={loading}
                        className="rounded-md px-2 py-1 text-xl leading-none text-slate-400 transition hover:bg-stone-100 hover:text-slate-700"
                    >
                        ×
                    </button>
                </div>

                <form
                    onSubmit={handleSubmit}
                    className="mt-6 space-y-5"
                >
                    <div>
                        <label
                            htmlFor="menu-item-name"
                            className="mb-2 block text-sm font-semibold text-slate-700"
                        >
                            Item Name
                        </label>

                        <input
                            id="menu-item-name"
                            type="text"
                            value={name}
                            onChange={(event) =>
                                setName(event.target.value)
                            }
                            placeholder="e.g. Pad Kra Pao"
                            disabled={loading}
                            className="w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none transition focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
                        />
                    </div>

                    <div>
                        <label
                            htmlFor="menu-item-description"
                            className="mb-2 block text-sm font-semibold text-slate-700"
                        >
                            Description
                        </label>

                        <textarea
                            id="menu-item-description"
                            value={description}
                            onChange={(event) =>
                                setDescription(event.target.value)
                            }
                            placeholder="Describe this menu item..."
                            rows={3}
                            disabled={loading}
                            className="w-full resize-none rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none transition focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
                        />
                    </div>

                    <div>
                        <label
                            htmlFor="menu-item-price"
                            className="mb-2 block text-sm font-semibold text-slate-700"
                        >
                            Price
                        </label>

                        <div className="relative">
                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-slate-400">
                                ฿
                            </span>

                            <input
                                id="menu-item-price"
                                type="number"
                                min="0"
                                step="0.01"
                                value={price}
                                onChange={(event) =>
                                    setPrice(event.target.value)
                                }
                                placeholder="0.00"
                                disabled={loading}
                                className="w-full rounded-md border border-slate-300 py-2.5 pl-8 pr-3 text-sm outline-none transition focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
                            />
                        </div>
                    </div>

                    <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-stone-50 p-4">
                        <div>
                            <p className="text-sm font-semibold text-slate-700">
                                Available
                            </p>

                            <p className="text-xs text-slate-500">
                                Customers can order this item.
                            </p>
                        </div>

                        <button
                            type="button"
                            onClick={() =>
                                setIsAvailable(!isAvailable)
                            }
                            disabled={loading}
                            className={`relative h-6 w-11 rounded-full transition duration-300 ${
                                isAvailable
                                    ? "bg-slate-950"
                                    : "bg-slate-300"
                            }`}
                        >
                            <span
                                className={`absolute top-1 h-4 w-4 rounded-full bg-white transition ${
                                    isAvailable
                                        ? "left-6"
                                        : "left-1"
                                }`}
                            />
                        </button>
                    </div>

                    {error && (
                        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600">
                            {error}
                        </p>
                    )}

                    <div className="flex justify-end gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={loading}
                            className="rounded-md border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-stone-50 disabled:opacity-50"
                        >
                            Cancel
                        </button>

                        <button
                            type="submit"
                            disabled={loading}
                            className="rounded-md bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {loading
                                ? isEditing
                                    ? "Saving..."
                                    : "Creating..."
                                : isEditing
                                    ? "Save Changes"
                                    : "Add Item"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
