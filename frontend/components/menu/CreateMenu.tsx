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
                className="rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-gray-800 cursor-pointer"
            >
                + Create Menu
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