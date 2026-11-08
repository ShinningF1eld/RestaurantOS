"""Bounded process-local business observations, with no exporter IO on writes."""

import logging
from typing import Literal, get_args

from opentelemetry.metrics import MeterProvider

SCOPE = "restaurantos.business"
TRANSITIONS = frozenset({"SUBMITTED", "COMPLETED", "CANCELLED"})
StockRejection = Literal[
    "order_item_unavailable",
    "order_recipe_invalid",
    "order_stock_insufficient",
    "inventory_inactive",
    "inventory_count_stale",
    "inventory_stock_insufficient",
    "inventory_balance_limit",
]
STOCK_REJECTIONS = frozenset(get_args(StockRejection))
logger = logging.getLogger("restaurantos.business")


class BusinessMetrics:
    def __init__(self, provider: MeterProvider) -> None:
        self.meter = provider.get_meter(SCOPE, "1")
        self.transitions = self.meter.create_counter(
            "restaurantos.business.orders.transitions",
            unit="{transition}",
            description="Observed committed order status transitions",
        )
        self.rejections = self.meter.create_counter(
            "restaurantos.business.stock.rejections",
            unit="{attempt}",
            description="Observed stock-related rejected command attempts",
        )


def order_transition(status: str) -> None:
    if status not in TRANSITIONS:
        return
    from app.core.telemetry import lifecycle

    try:
        active = lifecycle.runtime
        if active is not None:
            active.business_metrics.transitions.add(1, {"transition": status})
    except Exception:
        logger.warning("order transition observation failed")


def stock_rejection(category: StockRejection) -> None:
    if category not in STOCK_REJECTIONS:
        return
    from app.core.telemetry import lifecycle

    try:
        active = lifecycle.runtime
        if active is not None:
            active.business_metrics.rejections.add(1, {"category": category})
    except Exception:
        logger.warning("stock rejection observation failed")
