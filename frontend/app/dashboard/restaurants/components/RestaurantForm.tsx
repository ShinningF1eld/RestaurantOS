"use client";

import { FormEvent, useState } from "react";
import {
    Restaurant,
    RestaurantCreate,
} from "@/types/restaurant";

interface RestaurantFormProps {
    restaurant?: Restaurant;
    onSuccess: (data: RestaurantCreate) => void;
    onCancel: () => void;
}

export default function RestaurantForm({
    restaurant,
    onSuccess,
    onCancel,
}: RestaurantFormProps) {
    const [name, setName] = useState(restaurant?.name ?? "");
    const [address, setAddress] = useState(restaurant?.address ?? "");
    const [phone, setPhone] = useState(restaurant?.phone ?? "");
    const [loading, setLoading] = useState(false);
    const isEditMode = !!restaurant;

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        const data: RestaurantCreate = {
            name,
            address,
            phone,
        };

        setLoading(true);

        try {
            onSuccess(data);
        } finally {
            setLoading(false);
        }
    }

    return (
        <form
            onSubmit={handleSubmit}
            className="mb-6 rounded-lg border bg-white p-6 shadow-sm"
        >
            <h2 className="mb-4 text-xl font-semibold text-gray-900">
                {isEditMode ? "Edit Restaurant" : "Add Restaurant"}
            </h2>

            <div className="space-y-4 text-gray-900">
                <div>
                    <label className="mb-1 block text-sm font-medium text-gray-900">
                        Name
                    </label>

                    <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        required
                        className="w-full rounded-md border px-3 py-2 text-gray-900"
                        placeholder="Restaurant name "
                    />
                </div>

                <div>
                    <label className="mb-1 block text-sm font-medium">
                        Address
                    </label>

                    <input
                        type="text"
                        value={address}
                        onChange={(e) => setAddress(e.target.value)}
                        required
                        className="w-full rounded-md border px-3 py-2"
                        placeholder="Restaurant address"
                    />
                </div>

                <div>
                    <label className="mb-1 block text-sm font-medium">
                        Phone
                    </label>

                    <input
                        type="tel"
                        value={phone}
                        onChange={(e) => setPhone(e.target.value)}
                        required
                        className="w-full rounded-md border px-3 py-2"
                        placeholder="Phone number"
                    />
                </div>
            </div>

            <div className="mt-6 flex gap-3">
                <button
                    type="button"
                    onClick={onCancel}
                    className="rounded-md border px-4 py-2 text-gray-900"
                >
                    Cancel
                </button>

                <button
                    type="submit"
                    disabled={loading}
                    className="rounded-md bg-black px-4 py-2 text-white disabled:opacity-50"
                >
                    {loading
                        ? "Saving..."
                        : isEditMode
                            ? "Save Changes"
                            : "Create Restaurant"}
                </button>
            </div>
        </form>
    );
}