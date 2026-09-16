import PageHeader from "@/components/ui/PageHeader";
import StatCard from "@/components/ui/StatCard";
import StatusBadge from "@/components/ui/StatusBadge";

const employees = [
    {
        name: "Mina S.",
        role: "Server",
        station: "Main dining",
        shift: "15:00 - 23:00",
        status: "Clocked in",
    },
    {
        name: "Arun P.",
        role: "Bartender",
        station: "Bar",
        shift: "16:00 - 00:00",
        status: "Clocked in",
    },
    {
        name: "Nok W.",
        role: "Server",
        station: "Window",
        shift: "17:00 - 23:30",
        status: "Starting soon",
    },
    {
        name: "Dao K.",
        role: "Line cook",
        station: "Hot line",
        shift: "14:00 - 22:00",
        status: "Clocked in",
    },
    {
        name: "Ploy R.",
        role: "Host",
        station: "Front desk",
        shift: "18:00 - 23:00",
        status: "Scheduled",
    },
];

function getStatusTone(status: string) {
    if (status === "Clocked in") {
        return "green";
    }

    if (status === "Starting soon") {
        return "amber";
    }

    return "neutral";
}

export default function EmployeesPage() {
    const clockedIn = employees.filter((employee) => employee.status === "Clocked in");
    const servers = employees.filter((employee) => employee.role === "Server");

    return (
        <div className="space-y-8">
            <PageHeader
                eyebrow="Team"
                title="Employees"
                description="Coordinate shift coverage, active stations, and staff readiness for the current service."
                actions={<StatusBadge tone="blue">Mock staffing</StatusBadge>}
            />

            <div className="grid gap-4 md:grid-cols-4">
                <StatCard
                    label="Scheduled"
                    value={employees.length}
                    detail="People on today's roster"
                    tone="blue"
                />
                <StatCard
                    label="Clocked in"
                    value={clockedIn.length}
                    detail="Currently active"
                    tone="green"
                />
                <StatCard
                    label="Servers"
                    value={servers.length}
                    detail="Floor coverage"
                    tone="amber"
                />
                <StatCard
                    label="Open roles"
                    value="1"
                    detail="Runner needed at peak"
                    tone="red"
                />
            </div>

            <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
                <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
                    <div className="border-b border-slate-200 p-5">
                        <h2 className="text-lg font-semibold text-slate-950">
                            Shift Roster
                        </h2>
                        <p className="mt-1 text-sm text-slate-600">
                            Current service assignments and clock-in state.
                        </p>
                    </div>

                    <div className="divide-y divide-slate-100">
                        {employees.map((employee) => (
                            <div
                                key={employee.name}
                                className="grid gap-4 p-5 sm:grid-cols-[1fr_1fr_auto]"
                            >
                                <div>
                                    <p className="font-semibold text-slate-950">
                                        {employee.name}
                                    </p>
                                    <p className="mt-1 text-sm text-slate-600">
                                        {employee.role}
                                    </p>
                                </div>
                                <div>
                                    <p className="text-sm font-semibold text-slate-950">
                                        {employee.station}
                                    </p>
                                    <p className="mt-1 text-sm text-slate-600">
                                        {employee.shift}
                                    </p>
                                </div>
                                <div className="sm:text-right">
                                    <StatusBadge tone={getStatusTone(employee.status) as "green" | "amber" | "neutral"}>
                                        {employee.status}
                                    </StatusBadge>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
                    <h2 className="text-lg font-semibold text-slate-950">
                        Service Notes
                    </h2>
                    <div className="mt-5 space-y-4">
                        {[
                            "Assign a runner before the dinner rush.",
                            "Bar handoff needed at 22:00.",
                            "Host stand should confirm patio reservations.",
                        ].map((note) => (
                            <div
                                key={note}
                                className="rounded-lg border border-slate-200 bg-stone-50 p-4 text-sm leading-6 text-slate-700"
                            >
                                {note}
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
