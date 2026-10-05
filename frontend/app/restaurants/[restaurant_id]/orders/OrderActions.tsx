"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import {
    cancelOrder,
    updateOrder,
} from "@/lib/api/order";

import type { AccessContext } from "@/types/access";
import type { OrderStatus } from "@/types/order";

interface OrderActionsProps {
    orderId: number;
    status: string;
    access: AccessContext;
}

export default function OrderActions({
    orderId,
    status, access,
}: OrderActionsProps) {
    const router = useRouter();
    const [isUpdating, setIsUpdating] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const isClosed = status === "COMPLETED" || status === "CANCELLED";
    const nextStatus: Record<string, string> = {
        DRAFT: "SUBMITTED",
        SUBMITTED: "ACCEPTED",
        ACCEPTED: "PREPARING",
        PREPARING: "READY",
        READY: "COMPLETED",
    };

    const canAdvance = access.capabilities.includes("order.status.update") &&
        !isClosed && Boolean(nextStatus[status]) &&
        (access.role !== "EMPLOYEE" || status === "ACCEPTED" || status === "PREPARING");
    const canCancel = access.capabilities.includes("order.cancel") && !isClosed;

    async function updateStatus(
        action: "advance" | "cancel"
    ) {
        setIsUpdating(true);
        setError(null);

        try {
            if (action === "advance") {
                await updateOrder(orderId, { status: nextStatus[status] as OrderStatus });
            } else {
                await cancelOrder(orderId);
            }

            router.refresh();
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : "Could not update this order.");
            router.refresh();
        } finally {
            setIsUpdating(false);
        }
    }

    return (
        <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
                {canAdvance && <button
                    type="button"
                    disabled={isUpdating || isClosed}
                    onClick={() => updateStatus("advance")}
                    className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                    {nextStatus[status] ? `Mark ${nextStatus[status].toLowerCase()}` : "Complete"}
                </button>}

                {canCancel && <button
                    type="button"
                    disabled={isUpdating || isClosed}
                    onClick={() => updateStatus("cancel")}
                    className="rounded-md border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
                >
                    Cancel
                </button>}
            </div>

            {error ? (
                <p role="alert" className="text-xs text-red-600">
                    {error}
                </p>
            ) : null}
            {canCancel && <p className="text-xs text-slate-500">Cancelling does not return consumed ingredients to stock.</p>}
        </div>
    );
}
