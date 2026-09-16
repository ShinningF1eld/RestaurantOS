import type { ReactNode } from "react";

interface EmptyStateProps {
    title: string;
    description: string;
    action?: ReactNode;
}

export default function EmptyState({
    title,
    description,
    action,
}: EmptyStateProps) {
    return (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center">
            <div className="mx-auto h-10 w-10 rounded-lg border border-slate-200 bg-slate-50" />

            <h2 className="mt-4 text-lg font-semibold text-slate-950">
                {title}
            </h2>

            <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-600">
                {description}
            </p>

            {action ? (
                <div className="mt-6 flex justify-center">
                    {action}
                </div>
            ) : null}
        </div>
    );
}
