import PageHeader from "@/components/ui/PageHeader";
import StatCard from "@/components/ui/StatCard";
import StatusBadge from "@/components/ui/StatusBadge";

const inventoryItems = [
    {
        item: "Jasmine rice",
        category: "Dry goods",
        onHand: "18 kg",
        par: "25 kg",
        status: "Low",
        supplier: "Bangkok Pantry",
        nextDelivery: "Tomorrow",
    },
    {
        item: "Chicken thigh",
        category: "Protein",
        onHand: "32 kg",
        par: "28 kg",
        status: "OK",
        supplier: "Fresh Farms",
        nextDelivery: "Today 16:00",
    },
    {
        item: "Thai basil",
        category: "Produce",
        onHand: "1.5 kg",
        par: "3 kg",
        status: "Critical",
        supplier: "Morning Market",
        nextDelivery: "Today 14:00",
    },
    {
        item: "Coconut milk",
        category: "Dry goods",
        onHand: "42 cans",
        par: "36 cans",
        status: "OK",
        supplier: "Bangkok Pantry",
        nextDelivery: "Friday",
    },
    {
        item: "Limes",
        category: "Produce",
        onHand: "8 kg",
        par: "10 kg",
        status: "Watch",
        supplier: "Morning Market",
        nextDelivery: "Tomorrow",
    },
];

function getStatusTone(status: string) {
    if (status === "OK") {
        return "green";
    }

    if (status === "Critical") {
        return "red";
    }

    if (status === "Low" || status === "Watch") {
        return "amber";
    }

    return "neutral";
}

export default function InventoryPage() {
    const criticalItems = inventoryItems.filter((item) => item.status === "Critical");
    const lowItems = inventoryItems.filter((item) => item.status === "Low");
    const okItems = inventoryItems.filter((item) => item.status === "OK");

    return (
        <div className="space-y-8">
            <PageHeader
                eyebrow="Back of house"
                title="Inventory"
                description="Track stock levels, par targets, supplier timing, and ingredients that can affect service."
                actions={<StatusBadge tone="amber">Mock inventory</StatusBadge>}
            />

            <div className="grid gap-4 md:grid-cols-4">
                <StatCard
                    label="Tracked items"
                    value={inventoryItems.length}
                    detail="Across dry, protein, and produce"
                    tone="blue"
                />
                <StatCard
                    label="Critical"
                    value={criticalItems.length}
                    detail="Need immediate action"
                    tone="red"
                />
                <StatCard
                    label="Low"
                    value={lowItems.length}
                    detail="Below par"
                    tone="amber"
                />
                <StatCard
                    label="Healthy"
                    value={okItems.length}
                    detail="At or above par"
                    tone="green"
                />
            </div>

            <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
                <table className="w-full min-w-[760px] divide-y divide-slate-200 text-sm">
                    <thead className="bg-stone-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                        <tr>
                            <th className="px-5 py-3">Item</th>
                            <th className="px-5 py-3">Category</th>
                            <th className="px-5 py-3">On hand</th>
                            <th className="px-5 py-3">Par</th>
                            <th className="px-5 py-3">Status</th>
                            <th className="px-5 py-3">Supplier</th>
                            <th className="px-5 py-3">Next delivery</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                        {inventoryItems.map((item) => (
                            <tr key={item.item}>
                                <td className="px-5 py-4 font-semibold text-slate-950">
                                    {item.item}
                                </td>
                                <td className="px-5 py-4 text-slate-600">
                                    {item.category}
                                </td>
                                <td className="px-5 py-4 text-slate-950">
                                    {item.onHand}
                                </td>
                                <td className="px-5 py-4 text-slate-600">
                                    {item.par}
                                </td>
                                <td className="px-5 py-4">
                                    <StatusBadge tone={getStatusTone(item.status) as "green" | "red" | "amber" | "neutral"}>
                                        {item.status}
                                    </StatusBadge>
                                </td>
                                <td className="px-5 py-4 text-slate-600">
                                    {item.supplier}
                                </td>
                                <td className="px-5 py-4 text-slate-600">
                                    {item.nextDelivery}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
