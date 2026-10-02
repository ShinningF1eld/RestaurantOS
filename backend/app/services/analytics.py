"""Compatibility imports; implementation belongs to the feature module."""

from app.modules.analytics.service import (
    DashboardMetricData as DashboardMetricData,
    SalesPointData as SalesPointData,
    TopSellingItemData as TopSellingItemData,
    RestaurantDashboardAnalyticsData as RestaurantDashboardAnalyticsData,
    AnalyticsRepositoryPort as AnalyticsRepositoryPort,
    start_of_day as start_of_day,
    end_of_day as end_of_day,
    percent_change as percent_change,
    AnalyticsService as AnalyticsService,
)
