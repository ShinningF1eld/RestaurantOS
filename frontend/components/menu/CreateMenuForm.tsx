"use client";

import { FormEvent, useState } from "react";

import { createMenu } from "@/lib/api/menu";

interface CreateMenuFormProps {
    restaurantId: number;
    onClose: () => void;
    onSuccess: () => void;
}

export default function CreateMenuForm({
    restaurantId,
    onClose,
    onSuccess,
}: CreateMenuFormProps) {
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        if (!name.trim()) {
            setError("Menu name is required.");
            return;
        }

        try {
            setLoading(true);
            setError("");

            await createMenu(restaurantId, {
                name: name.trim(),
                description: description.trim() || null,
            });

            onSuccess();
        } catch (error) {
            console.error(error);
            setError("Failed to create menu.");
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
                {/* Header */}
                <div className="flex items-start justify-between">
                    <div>
                        <h2 className="text-xl font-semibold text-gray-900">
                            Create Menu
                        </h2>

                        <p className="mt-1 text-sm text-gray-500">
                            Add a new menu for your restaurant.
                        </p>
                    </div>

                    <button
                        type="button"
                        onClick={onClose}
                        className="text-xl text-gray-400 transition hover:text-gray-600 cursor-pointer"
                    >
                        ×
                    </button>
                </div>

                {/* Form */}
                <form
                    onSubmit={handleSubmit}
                    className="mt-6 space-y-5"
                >
                    {/* Name */}
                    <div>
                        <label
                            htmlFor="menu-name"
                            className="mb-2 block text-sm font-medium text-gray-700"
                        >
                            Menu Name
                        </label>

                        <input
                            id="menu-name"
                            type="text"
                            value={name}
                            onChange={(event) =>
                                setName(event.target.value)
                            }
                            placeholder="e.g. Main Menu"
                            className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition focus:border-gray-900 focus:ring-1 focus:ring-gray-900"
                            disabled={loading}
                        />
                    </div>

                    {/* Description */}
                    <div>
                        <label
                            htmlFor="menu-description"
                            className="mb-2 block text-sm font-medium text-gray-700"
                        >
                            Description
                        </label>

                        <textarea
                            id="menu-description"
                            value={description}
                            onChange={(event) =>
                                setDescription(event.target.value)
                            }
                            placeholder="Describe this menu..."
                            rows={4}
                            className="w-full resize-none rounded-lg border px-3 py-2.5 text-sm outline-none transition focus:border-gray-900 focus:ring-1 focus:ring-gray-900"
                            disabled={loading}
                        />
                    </div>

                    {/* Error */}
                    {error && (
                        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
                            {error}
                        </p>
                    )}

                    {/* Actions */}
                    <div className="flex justify-end gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={loading}
                            className="rounded-lg border px-4 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-50 cursor-pointer"
                        >
                            Cancel
                        </button>

                        <button
                            type="submit"
                            disabled={loading}
                            className="rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
                        >
                            {loading ? "Creating..." : "Create Menu"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}