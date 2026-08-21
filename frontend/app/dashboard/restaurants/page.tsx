"use client";

import { useEffect, useState } from "react";
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

export default function RestaurantsPage() {
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
            } catch (err) {
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
        } catch (err) {
            setError("Failed to create restaurant");
        }
    }

    if (loading) {
        return <div className="p-8">Loading restaurants...</div>;
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
        } catch (err) {
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
        } catch (err) {
            setError("Failed to update restaurant");
        }
    }

    return (
        <main className="min-h-screen bg-gray-50 p-8">
            <div className="mx-auto max-w-4xl">

                <div className="mb-6 flex items-center justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">
                            Restaurants
                        </h1>

                        <p className="mt-1 text-gray-500">
                            Manage your restaurants
                        </p>
                    </div>

                    <button
                        onClick={() => setShowForm(true)}
                        className="rounded-md bg-black px-4 py-2 text-white cursor-pointer"
                    >
                        + Add Restaurant
                    </button>
                </div>

                {error && (
                    <div className="mb-4 rounded-md bg-red-100 p-4 text-red-700">
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

                <div className="space-y-4">
                    {restaurants.map((restaurant) => (
                        <div
                            key={restaurant.id}
                            className="rounded-lg border bg-white p-5 shadow-sm"
                        >
                            <div className="flex items-start justify-between text-gray-900">
                                <div>
                                    <h2 className="text-xl font-semibold">
                                        {restaurant.name}
                                    </h2>

                                    <p className="mt-2 text-gray-600">
                                        {restaurant.address}
                                    </p>

                                    <p className="mt-1 text-gray-500">
                                        {restaurant.phone}
                                    </p>
                                </div>
                                <div className="flex gap-2">
                                    <button
                                        onClick={() => setEditingRestaurant(restaurant)}
                                        className="rounded-md bg-blue-500 px-3 py-2 text-sm text-white cursor-pointer"
                                    >
                                        Edit
                                    </button>

                                    <button
                                        onClick={() => handleDelete(restaurant.id)}
                                        className="rounded-md bg-red-500 px-3 py-2 text-sm text-white cursor-pointer hover:bg-red-600"
                                    >
                                        Delete
                                    </button>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {restaurants.length === 0 && (
                <div className="rounded-lg border bg-white p-8 text-center text-gray-500">
                    No restaurants found.
                </div>
            )}
        </main >
    );
}