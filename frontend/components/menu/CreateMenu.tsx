"use client";

import { useState } from "react";

import CreateMenuForm from "./CreateMenuForm";

interface CreateMenuProps {
    restaurantId: number;
}

export default function CreateMenu({
    restaurantId,
}: CreateMenuProps) {
    const [isOpen, setIsOpen] = useState(false);

    function handleSuccess() {
        setIsOpen(false);
        window.location.reload();
    }

    return (
        <>
            <button
                type="button"
                onClick={() => setIsOpen(true)}
                className="rounded-md bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800"
            >
                Create menu
            </button>

            {isOpen && (
                <CreateMenuForm
                    restaurantId={restaurantId}
                    onClose={() => setIsOpen(false)}
                    onSuccess={handleSuccess}
                />
            )}
        </>
    );
}
