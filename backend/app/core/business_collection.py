"""Optional operator aggregates from one read-only PostgreSQL snapshot."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Lock

from opentelemetry.metrics import Meter, _Gauge
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.modules.alerts.service import operator_active_low_stock_alerts
from app.modules.analytics.service import operator_completed_sales
from app.modules.events.domain.diagnostics import BACKLOG_STATES
from app.modules.events.service import operator_analytics_backlog
from app.modules.inventory.service import operator_low_stock_summary

logger = logging.getLogger("restaurantos.business")


@dataclass(frozen=True, slots=True)
class BusinessSnapshot:
    as_of: datetime
    completed_orders: int
    sales_thb: Decimal | None
    operational_openings: int
    baseline_openings: int
    active_ingredients: int
    active_alerts: int
    analytics_backlog: dict[str, tuple[int, float]]


async def read_snapshot(
    sessions: async_sessionmaker[AsyncSession], *, include_thb: bool
) -> BusinessSnapshot:
    async with sessions() as session, session.begin():
        await session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        await session.execute(text("SET LOCAL statement_timeout = '1000ms'"))
        sampled_at = (
            await session.execute(text("SELECT transaction_timestamp()"))
        ).scalar_one()
        as_of = sampled_at.astimezone(UTC)
        orders, sales = await operator_completed_sales(
            session, as_of.date(), include_thb=include_thb
        )
        openings, baselines, active = await operator_low_stock_summary(
            session, as_of - timedelta(hours=24), as_of
        )
        alerts = await operator_active_low_stock_alerts(session)
        backlog = await operator_analytics_backlog(session)
    return BusinessSnapshot(
        as_of=as_of,
        completed_orders=orders,
        sales_thb=sales,
        operational_openings=openings,
        baseline_openings=baselines,
        active_ingredients=active,
        active_alerts=alerts,
        analytics_backlog={
            row.state: (row.depth, row.oldest_seconds) for row in backlog
        },
    )


class BusinessCollector:
    def __init__(self, meter: Meter, settings: Settings) -> None:
        self.settings = settings
        self._running = Lock()

        def gauge(name: str, description: str, unit: str) -> _Gauge:
            return meter.create_gauge(
                "restaurantos.business." + name, unit=unit, description=description
            )

        self.orders = gauge(
            "sales.retained_orders_7d",
            "Projected retained completed orders created today or in the previous six UTC dates",
            "{order}",
        )
        self.sales = (
            gauge(
                "sales.retained_amount_7d",
                "Projected retained completed-order amounts for today and the previous six UTC creation dates",
                "THB",
            )
            if settings.monitoring_business_sales_thb
            else None
        )
        self.openings = gauge(
            "stock.episode_openings_24h",
            "Durable episode openings in extant restaurant scopes over the preceding 24 hours",
            "{episode}",
        )
        self.ingredients = gauge(
            "stock.active_ingredients",
            "Live active low-stock ingredients",
            "{ingredient}",
        )
        self.alerts = gauge(
            "stock.active_alerts",
            "Projected active alerts still matching live episodes",
            "{alert}",
        )
        self.deliveries = gauge(
            "analytics.deliveries",
            "Retained unfinished or failed analytics deliveries",
            "{delivery}",
        )
        self.oldest = gauge(
            "analytics.oldest", "Oldest delivery age at source collection by state", "s"
        )
        self.collected = gauge(
            "collection.last_success",
            "Unix time of the last successful PostgreSQL snapshot",
            "s",
        )
        self.success = gauge(
            "collection.success",
            "Whether the last PostgreSQL collection attempt succeeded",
            "",
        )
        freshness_budget = gauge(
            "collection.freshness_budget",
            "Maximum acceptable age of a successful PostgreSQL snapshot",
            "s",
        )
        # Allow two collection intervals, one export interval, and ten seconds
        # for the Collector batch and Prometheus scrape.
        freshness_budget.set(
            2 * settings.monitoring_business_collection_seconds
            + settings.monitoring_export_interval_ms / 1000
            + 10
        )
        self.success.set(0)

    async def collect(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        try:
            async with asyncio.timeout(3):
                sample = await read_snapshot(
                    sessions, include_thb=self.settings.monitoring_business_sales_thb
                )
            self.orders.set(sample.completed_orders)
            if self.sales is not None and sample.sales_thb is not None:
                self.sales.set(float(sample.sales_thb))
            self.openings.set(sample.operational_openings, {"kind": "operational"})
            self.openings.set(sample.baseline_openings, {"kind": "baseline"})
            self.ingredients.set(sample.active_ingredients)
            self.alerts.set(sample.active_alerts)
            for state in BACKLOG_STATES:
                count, age = sample.analytics_backlog.get(state, (0, 0.0))
                self.deliveries.set(count, {"state": state})
                self.oldest.set(age, {"state": state})
            self.collected.set(sample.as_of.timestamp())
            self.success.set(1)
        except Exception:
            # Never log driver errors or SQL parameters. Keep the last timestamp
            # and mark any retained points unusable until the next good sample.
            logger.warning("business metric collection failed")
            try:
                self.success.set(0)
            except Exception:
                pass

    async def run(self) -> None:
        interval = self.settings.monitoring_business_collection_seconds
        # Overlapping lifespans can share a telemetry runtime across event loops.
        while not self._running.acquire(blocking=False):
            await asyncio.sleep(interval)
        try:
            # A single sampler uses at most one connection outside the API pool.
            engine = create_async_engine(
                self.settings.database_url,
                hide_parameters=True,
                poolclass=NullPool,
                connect_args={"timeout": 2, "command_timeout": 2},
            )
            try:
                sessions = async_sessionmaker(engine)
                while True:
                    await self.collect(sessions)
                    await asyncio.sleep(interval)
            finally:
                await engine.dispose()
        except Exception:
            logger.warning("business metric sampler stopped")
        finally:
            self._running.release()
