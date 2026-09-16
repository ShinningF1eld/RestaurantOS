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
            className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
        >
            <div className="border-b border-slate-200 pb-4">
                <h2 className="text-xl font-semibold text-slate-950">
                    {isEditMode ? "Edit Restaurant" : "Add Restaurant"}
                </h2>

                <p className="mt-1 text-sm text-slate-600">
                    Keep location information accurate for floor and service teams.
                </p>
            </div>

            <div className="mt-5 grid gap-4 text-slate-950 md:grid-cols-3">
                <div>
                    <label className="mb-2 block text-sm font-semibold text-slate-700">
                        Name
                    </label>

                    <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        required
                        className="w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm text-slate-950 outline-none transition focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
                        placeholder="Restaurant name "
                    />
                </div>

                <div>
                    <label className="mb-2 block text-sm font-semibold text-slate-700">
                        Address
                    </label>

                    <input
                        type="text"
                        value={address}
                        onChange={(e) => setAddress(e.target.value)}
                        required
                        className="w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none transition focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
                        placeholder="Restaurant address"
                    />
                </div>

                <div>
                    <label className="mb-2 block text-sm font-semibold text-slate-700">
                        Phone
                    </label>

                    <input
                        type="tel"
                        value={phone}
                        onChange={(e) => setPhone(e.target.value)}
                        required
                        className="w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none transition focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
                        placeholder="Phone number"
                    />
                </div>
            </div>

            <div className="mt-6 flex gap-3">
                <button
                    type="button"
                    onClick={onCancel}
                    className="rounded-md border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-stone-50"
                >
                    Cancel
                </button>

                <button
                    type="submit"
                    disabled={loading}
                    className="rounded-md bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50"
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
