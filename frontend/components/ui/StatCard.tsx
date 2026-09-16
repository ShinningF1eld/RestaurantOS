import type { ReactNode } from "react";

interface StatCardProps {
    label: string;
    value: ReactNode;
    detail?: ReactNode;
    tone?: "neutral" | "green" | "amber" | "red" | "blue";
}

const toneClasses = {
    neutral: "border-slate-200 bg-white",
    green: "border-emerald-200 bg-emerald-50",
    amber: "border-amber-200 bg-amber-50",
    red: "border-red-200 bg-red-50",
    blue: "border-sky-200 bg-sky-50",
};

export default function StatCard({
    label,
    value,
    detail,
    tone = "neutral",
}: StatCardProps) {
    return (
        <div className={`rounded-lg border p-5 shadow-sm ${toneClasses[tone]}`}>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {label}
            </p>

            <div className="mt-3 text-2xl font-semibold tracking-tight text-slate-950">
                {value}
            </div>

            {detail ? (
                <div className="mt-2 text-sm text-slate-600">
                    {detail}
                </div>
            ) : null}
        </div>
    );
}
