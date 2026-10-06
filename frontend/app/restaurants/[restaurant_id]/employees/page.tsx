import { getAccess, getMemberships } from "@/lib/api/server";
import PageHeader from "@/components/ui/PageHeader";
import StaffPanel from "@/features/tenancy/StaffPanel";

export default async function EmployeesPage({
  params,
}: {
  params: Promise<{ restaurant_id: string }>;
}) {
  const { restaurant_id } = await params;
  const access = await getAccess();
  if (!access.capabilities.includes("staff.manage")) {
    return <p role="alert">Only an owner can manage staff access.</p>;
  }
  const members = await getMemberships();
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Organization"
        title="Staff access"
        description="Assign provisioned accounts and manage access across your organization."
      />
      <StaffPanel initialMembers={members} restaurantId={Number(restaurant_id)} />
    </div>
  );
}
