import type { ReactNode } from "react";

interface StatusBadgeProps {
    children: ReactNode;
    tone?: "neutral" | "green" | "amber" | "red" | "blue";
}

const toneClasses = {
    neutral: "bg-slate-100 text-slate-700 ring-slate-200",
    green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
    red: "bg-red-50 text-red-700 ring-red-200",
    blue: "bg-sky-50 text-sky-700 ring-sky-200",
};

export default function StatusBadge({
    children,
    tone = "neutral",
}: StatusBadgeProps) {
    return (
        <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${toneClasses[tone]}`}>
            {children}
        </span>
    );
}
