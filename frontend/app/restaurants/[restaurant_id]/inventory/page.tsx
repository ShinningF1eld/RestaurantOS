import { getAccess } from "@/lib/api/server";
import InventoryManager from "@/features/inventory/InventoryManager";
import PageHeader from "@/components/ui/PageHeader";

export default async function InventoryPage({
  params,
}: {
  params: Promise<{ restaurant_id: string }>;
}) {
  const { restaurant_id } = await params;
  const access = await getAccess();
  if (!access.capabilities.includes("inventory.read"))
    return <p role="alert">Inventory is unavailable for your role.</p>;
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Back of house"
        title="Inventory"
        description="Manage ingredients, receive stock, record waste, and reconcile physical counts."
      />
      <InventoryManager
        key={restaurant_id}
        restaurantId={Number(restaurant_id)}
        canManage={access.capabilities.includes("inventory.manage")}
      />
    </div>
  );
}
