"use client";

import { useEffect } from "react";

export default function RestaurantWorkspaceError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    useEffect(() => {
        console.error("Restaurant workspace failed to load", error);
    }, [error]);

    return (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
            <h1 className="text-lg font-semibold text-red-950">Restaurant workspace unavailable</h1>
            <p className="mx-auto mt-2 max-w-md text-sm text-red-800">
                We could not load the latest restaurant data. Check the API connection and try again.
            </p>
            <button type="button" onClick={reset} className="mt-4 rounded-md bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800">
                Try again
            </button>
        </div>
    );
}
