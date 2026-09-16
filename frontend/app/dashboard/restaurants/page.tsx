"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
    createRestaurant,
    getRestaurants,
    deleteRestaurant,
    updateRestaurant,
} from "@/lib/api/restaurant";
import {
    Restaurant,
    RestaurantCreate,
    RestaurantUpdate,
} from "@/types/restaurant";
import RestaurantForm from "./components/RestaurantForm";
import PageHeader from "@/components/ui/PageHeader";
import StatCard from "@/components/ui/StatCard";
import StatusBadge from "@/components/ui/StatusBadge";

export default function RestaurantsPage() {
    const router = useRouter();
    const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [showForm, setShowForm] = useState(false);
    const [editingRestaurant, setEditingRestaurant] =
        useState<Restaurant | null>(null);

    useEffect(() => {
        async function loadRestaurants() {
            try {
                const data = await getRestaurants();
                setRestaurants(data);
            } catch {
                setError("Failed to load restaurants");
            } finally {
                setLoading(false);
            }
        }

        loadRestaurants();
    }, []);

    async function handleCreate(data: RestaurantCreate) {
        try {
            const newRestaurant = await createRestaurant(data);

            setRestaurants((current) => [
                ...current,
                newRestaurant,
            ]);

            setShowForm(false);
        } catch {
            setError("Failed to create restaurant");
        }
    }

    if (loading) {
        return (
            <main className="min-h-screen bg-stone-50 p-8 text-slate-950">
                <div className="mx-auto max-w-7xl">
                    <div className="rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
                        Loading restaurants...
                    </div>
                </div>
            </main>
        );
    }

    async function handleDelete(id: number) {
        const confirmed = window.confirm(
            "Are you sure you want to delete this restaurant?"
        );

        if (!confirmed) {
            return;
        }

        try {
            await deleteRestaurant(id);

            setRestaurants((current) =>
                current.filter((restaurant) => restaurant.id !== id)
            );
        } catch {
            setError("Failed to delete restaurant");
        }
    }

    async function handleUpdate(
        id: number,
        data: RestaurantUpdate
    ) {
        try {
            const updatedRestaurant = await updateRestaurant(id, data);

            setRestaurants((current) =>
                current.map((restaurant) =>
                    restaurant.id === id
                        ? updatedRestaurant
                        : restaurant
                )
            );
        } catch {
            setError("Failed to update restaurant");
        }
    }

    return (
        <main className="min-h-screen bg-stone-50 p-4 text-slate-950 sm:p-6 lg:p-8">
            <div className="mx-auto max-w-7xl space-y-8">
                <header className="flex items-center justify-between border-b border-slate-200 pb-6">
                    <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-md bg-slate-950 text-sm font-semibold text-white">
                            OS
                        </div>
                        <div>
                            <p className="text-sm font-semibold">
                                RestaurantOS
                            </p>
                            <p className="text-xs text-slate-500">
                                Multi-location workspace
                            </p>
                        </div>
                    </div>

                    <Link
                        href="/"
                        className="text-sm font-semibold text-slate-600 transition hover:text-slate-950"
                    >
                        Home
                    </Link>
                </header>

                <PageHeader
                    eyebrow="Workspace"
                    title="Restaurants"
                    description="Choose a location, update profile information, or add a new restaurant to the operations console."
                    actions={(
                    <button
                        onClick={() => setShowForm(true)}
                        className="rounded-md bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800"
                    >
                        Add restaurant
                    </button>
                    )}
                />

                <div className="grid gap-4 md:grid-cols-3">
                    <StatCard
                        label="Locations"
                        value={restaurants.length}
                        detail="Configured restaurants"
                        tone="blue"
                    />
                    <StatCard
                        label="Active operations"
                        value={restaurants.length}
                        detail="Ready for dashboard access"
                        tone="green"
                    />
                    <StatCard
                        label="Setup tasks"
                        value="3"
                        detail="Mock onboarding checks"
                        tone="amber"
                    />
                </div>

                {error && (
                    <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                        {error}
                    </div>
                )}

                {showForm && (
                    <RestaurantForm
                        onSuccess={handleCreate}
                        onCancel={() => setShowForm(false)}
                    />
                )}

                {editingRestaurant && (
                    <RestaurantForm
                        restaurant={editingRestaurant}
                        onSuccess={(data) =>
                            handleUpdate(editingRestaurant.id, data)
                        }
                        onCancel={() => setEditingRestaurant(null)}
                    />
                )}

                {restaurants.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-600">
                        No restaurants found.
                    </div>
                ) : (
                    <div className="grid gap-4 lg:grid-cols-2">
                        {restaurants.map((restaurant) => (
                            <div
                                key={restaurant.id}
                                onClick={() =>
                                    router.push(
                                        `/restaurants/${restaurant.id}/dashboard`
                                    )
                                }
                                className="cursor-pointer rounded-lg border border-slate-200 bg-white p-5 shadow-sm transition duration-200 hover:border-slate-300 hover:shadow-md"
                            >
                                <div className="flex items-start justify-between gap-4 text-slate-950">
                                    <div>
                                        <div className="flex flex-wrap items-center gap-3">
                                            <h2 className="text-xl font-semibold">
                                                {restaurant.name}
                                            </h2>
                                            <StatusBadge tone="green">Active</StatusBadge>
                                        </div>

                                        <p className="mt-3 text-sm leading-6 text-slate-600">
                                            {restaurant.address}
                                        </p>

                                        <p className="mt-1 text-sm text-slate-500">
                                            {restaurant.phone}
                                        </p>
                                    </div>
                                    <div className="flex shrink-0 gap-2">
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setEditingRestaurant(restaurant);
                                            }}
                                            className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-stone-50"
                                        >
                                            Edit
                                        </button>

                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleDelete(restaurant.id);
                                            }}
                                            className="rounded-md border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-50"
                                        >
                                            Delete
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </main >
    );
}
