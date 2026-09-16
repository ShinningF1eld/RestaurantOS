import type { ReactNode } from "react";

interface PageHeaderProps {
    eyebrow?: string;
    title: string;
    description: string;
    actions?: ReactNode;
}

export default function PageHeader({
    eyebrow,
    title,
    description,
    actions,
}: PageHeaderProps) {
    return (
        <div className="flex flex-col gap-4 border-b border-slate-200 pb-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
                {eyebrow ? (
                    <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
                        {eyebrow}
                    </p>
                ) : null}

                <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">
                    {title}
                </h1>

                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
                    {description}
                </p>
            </div>

            {actions ? (
                <div className="flex flex-wrap items-center gap-3">
                    {actions}
                </div>
            ) : null}
        </div>
    );
}
