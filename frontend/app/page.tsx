
import Link from "next/link";

export const dynamic = "force-dynamic";

async function getData() {
  try {
    const response = await fetch("http://localhost:8000/api/test")

    if (!response.ok) {
      throw new Error("Failed to Fetch API");
    }

    return response.json()
  } catch {
    return {
      message: "Backend API offline",
    };
  }
}

export default async function Home() {

  const data = await getData()
 
  return (
    <main className="min-h-screen bg-stone-50 px-6 py-8 text-slate-950">
      <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-6xl flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 pb-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
              Restaurant operations
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">
              RestaurantOS
            </h1>
          </div>

          <Link
            href="/dashboard/restaurants"
            className="rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800"
          >
            Open workspace
          </Link>
        </header>

        <section className="grid flex-1 items-center gap-8 py-12 lg:grid-cols-[1.05fr_0.95fr]">
          <div>
            <p className="text-sm font-medium text-emerald-700">
              API status: {data.message}
            </p>

            <h2 className="mt-4 max-w-3xl text-4xl font-semibold tracking-tight text-slate-950 sm:text-5xl">
              Run service, tables, menus, stock, and staff from one quiet command center.
            </h2>

            <p className="mt-5 max-w-2xl text-base leading-7 text-slate-600">
              Built for restaurant teams that need fast context, fewer tabs, and clean operational handoffs from floor to kitchen to back office.
            </p>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="grid grid-cols-2 gap-3">
              {[
                ["Open orders", "18"],
                ["Tables seated", "12"],
                ["Low stock", "5"],
                ["Staff on shift", "9"],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="rounded-lg border border-slate-200 bg-stone-50 p-4"
                >
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {label}
                  </p>
                  <p className="mt-3 text-3xl font-semibold text-slate-950">
                    {value}
                  </p>
                </div>
              ))}
            </div>

            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
              <p className="text-sm font-semibold text-amber-900">
                Dinner readiness
              </p>
              <div className="mt-3 h-2 rounded-full bg-amber-100">
                <div className="h-2 w-4/5 rounded-full bg-amber-500" />
              </div>
              <p className="mt-3 text-sm text-amber-800">
                Kitchen prep is on track. Two inventory items need manager review.
              </p>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
