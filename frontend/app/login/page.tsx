import LoginForm from "@/features/auth/LoginForm";
import { safeReturnPath } from "@/features/auth/paths";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <section className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-semibold text-amber-700">RestaurantOS</p>
        <h1 className="mt-3 text-3xl font-semibold">Welcome back</h1>
        <p className="mb-8 mt-3 text-sm text-slate-600">
          Sign in with the account provided by your administrator.
        </p>
        <LoginForm next={safeReturnPath(next)} />
      </section>
    </main>
  );
}
