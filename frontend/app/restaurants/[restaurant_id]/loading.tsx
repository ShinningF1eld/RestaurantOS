export default function RestaurantWorkspaceLoading() {
    return (
        <div className="min-h-screen animate-pulse bg-stone-50 p-6 sm:p-8">
            <div className="mx-auto max-w-7xl space-y-6">
                <div className="h-16 rounded-lg bg-slate-200" />
                <div className="grid gap-4 md:grid-cols-3">
                    <div className="h-28 rounded-lg bg-slate-200" />
                    <div className="h-28 rounded-lg bg-slate-200" />
                    <div className="h-28 rounded-lg bg-slate-200" />
                </div>
                <div className="h-64 rounded-lg bg-slate-200" />
            </div>
        </div>
    );
}
