import Link from "next/link";

export default function RestaurantNotFound() {
    return (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center">
            <h1 className="text-xl font-semibold text-slate-950">Restaurant not found</h1>
            <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
                This restaurant may have been deleted or the link is no longer valid.
            </p>
            <Link href="/dashboard/restaurants" className="mt-5 inline-flex rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800">
                Return to restaurants
            </Link>
        </div>
    );
}
