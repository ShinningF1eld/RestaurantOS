"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import {
    cancelOrder,
    completeOrder,
} from "@/lib/api/order";

interface OrderActionsProps {
    orderId: number;
    status: string;
}

export default function OrderActions({
    orderId,
    status,
}: OrderActionsProps) {
    const router = useRouter();
    const [isUpdating, setIsUpdating] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const isClosed = status === "complete" || status === "cancelled";

    async function updateStatus(
        action: "complete" | "cancel"
    ) {
        setIsUpdating(true);
        setError(null);

        try {
            if (action === "complete") {
                await completeOrder(orderId);
            } else {
                await cancelOrder(orderId);
            }

            router.refresh();
        } catch {
            setError("Could not update this order.");
        } finally {
            setIsUpdating(false);
        }
    }

    return (
        <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
                <button
                    type="button"
                    disabled={isUpdating || isClosed}
                    onClick={() => updateStatus("complete")}
                    className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-gray-300"
                >
                    Complete
                </button>

                <button
                    type="button"
                    disabled={isUpdating || isClosed}
                    onClick={() => updateStatus("cancel")}
                    className="rounded-md border border-red-200 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                >
                    Cancel
                </button>
            </div>

            {error ? (
                <p className="text-xs text-red-600">
                    {error}
                </p>
            ) : null}
        </div>
    );
}
