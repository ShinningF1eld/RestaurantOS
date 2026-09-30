import RenewSession from "@/features/auth/RenewSession";
import { safeReturnPath } from "@/features/auth/paths";

export default async function RenewPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  return <main className="mx-auto max-w-lg p-8"><h1 className="mb-5 text-2xl font-semibold">RestaurantOS session</h1><RenewSession next={safeReturnPath(next)} /></main>;
}
