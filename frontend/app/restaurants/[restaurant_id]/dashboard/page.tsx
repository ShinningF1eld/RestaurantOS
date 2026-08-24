export default function DashboardPage() {
    return (
        <div className="space-y-8">
            {/* Header */}
            <div>
                <h1 className="text-2xl font-bold">
                    Good afternoon, Manager
                </h1>

                <p className="mt-1 text-sm text-gray-500">
                    Here's what's happening today.
                </p>
            </div>

            {/* Statistics */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <div className="rounded-xl border bg-white p-6 shadow-sm">
                    <p className="text-sm text-gray-500">
                        Sales
                    </p>

                    <p className="mt-2 text-3xl font-bold">
                         MOCK ฿24,580
                    </p>

                    <p className="mt-2 text-sm text-green-600">
                        MOCK +12.5%
                    </p>
                </div>

                <div className="rounded-xl border bg-white p-6 shadow-sm">
                    <p className="text-sm text-gray-500">
                        Orders
                    </p>

                    <p className="mt-2 text-3xl font-bold">
                        MOCK 126
                    </p>

                    <p className="mt-2 text-sm text-green-600">
                        MOCK +8.2%
                    </p>
                </div>

                <div className="rounded-xl border bg-white p-6 shadow-sm">
                    <p className="text-sm text-gray-500">
                        Average Order
                    </p>

                    <p className="mt-2 text-3xl font-bold">
                        MOCK ฿195
                    </p>

                    <p className="mt-2 text-sm text-green-600">
                        MOCK +3.1%
                    </p>
                </div>
            </div>

            {/* Sales + Low Stock */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
                {/* Sales Chart */}
                <div className="rounded-xl border bg-white p-6 shadow-sm lg:col-span-2">
                    <div className="mb-6">
                        <h2 className="text-lg font-semibold">
                            Sales
                        </h2>

                        <p className="text-sm text-gray-500">
                            Sales performance over time
                        </p>
                    </div>

                    <div className="flex h-72 items-center justify-center rounded-lg bg-gray-50">
                        <span className="text-sm text-gray-400">
                            Sales chart will go here
                        </span>
                    </div>
                </div>

                {/* Low Stock */}
                <div className="rounded-xl border bg-white p-6 shadow-sm">
                    <div className="mb-6">
                        <h2 className="text-lg font-semibold">
                            Low Stock
                        </h2>

                        <p className="text-sm text-gray-500">
                            Items that need attention
                        </p>
                    </div>

                    <div className="space-y-4">
                        <div className="flex items-center justify-between">
                            <span className="text-sm">
                                MOCK Chicken
                            </span>

                            <span className="text-sm font-medium text-red-600">
                                MOCK Low
                            </span>
                        </div>

                        <div className="flex items-center justify-between">
                            <span className="text-sm">
                                MOCK Basil
                            </span>

                            <span className="text-sm font-medium text-red-600">
                                MOCK Low
                            </span>
                        </div>

                        <div className="flex items-center justify-between">
                            <span className="text-sm">
                                MOCK Rice
                            </span>

                            <span className="text-sm font-medium text-yellow-600">
                                MOCK Warning
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Top Selling Items */}
            <div className="rounded-xl border bg-white p-6 shadow-sm">
                <div className="mb-6">
                    <h2 className="text-lg font-semibold">
                        Top Selling Items
                    </h2>

                    <p className="text-sm text-gray-500">
                        Best-selling menu items
                    </p>
                </div>

                <div className="divide-y">
                    <div className="flex items-center justify-between py-4">
                        <div className="flex items-center gap-4">
                            <span className="w-6 text-sm font-medium text-gray-400">
                                1
                            </span>

                            <span className="font-medium">
                                MOCK Pad Kra Pao
                            </span>
                        </div>

                        <span className="text-sm text-gray-500">
                            MOCK 238 sold
                        </span>
                    </div>

                    <div className="flex items-center justify-between py-4">
                        <div className="flex items-center gap-4">
                            <span className="w-6 text-sm font-medium text-gray-400">
                                2
                            </span>

                            <span className="font-medium">
                                MOCK Thai Tea
                            </span>
                        </div>

                        <span className="text-sm text-gray-500">
                            MOCK 194 sold
                        </span>
                    </div>

                    <div className="flex items-center justify-between py-4">
                        <div className="flex items-center gap-4">
                            <span className="w-6 text-sm font-medium text-gray-400">
                                3
                            </span>

                            <span className="font-medium">
                                MOCK Tom Yum
                            </span>
                        </div>

                        <span className="text-sm text-gray-500">
                            MOCK 151 sold
                        </span>
                    </div>
                </div>
            </div>
        </div>
    );
}