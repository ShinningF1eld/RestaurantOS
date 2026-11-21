"""Read durable delivery state even when no worker is running."""

import asyncio
import logging
from threading import Lock
from time import time

from opentelemetry.metrics import MeterProvider
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.modules.events.domain.diagnostics import BACKLOG_STATES
from app.modules.events.repo.worker_queries import backlog_samples
from app.modules.events.telemetry import CONSUMERS

logger = logging.getLogger("restaurantos.delivery_sampler")
INTERVAL = 15


class DeliverySampler:
    def __init__(self, provider: MeterProvider, settings: Settings) -> None:
        self.settings = settings
        self.running = Lock()
        meter = provider.get_meter("restaurantos.events", "1")
        self.depth = meter.create_gauge(
            "restaurantos.delivery.depth", unit="{delivery}"
        )
        self.age = meter.create_gauge("restaurantos.delivery.oldest", unit="s")
        self.collected = meter.create_gauge("restaurantos.delivery.collected", unit="s")

    async def run(self) -> None:
        # Overlapping API lifespans share a provider across event loops.
        while not self.running.acquire(blocking=False):
            await asyncio.sleep(INTERVAL)
        try:
            engine = create_async_engine(
                self.settings.database_url,
                hide_parameters=True,
                poolclass=NullPool,
                connect_args={"timeout": 2, "command_timeout": 2},
            )
            try:
                sessions = async_sessionmaker(engine)
                while True:
                    try:
                        async with asyncio.timeout(3):
                            async with sessions.begin() as session:
                                await session.execute(text("SET TRANSACTION READ ONLY"))
                                rows = await backlog_samples(session)
                        grouped = {(row.consumer, row.state): row for row in rows}
                        for consumer in CONSUMERS:
                            for state in BACKLOG_STATES:
                                row = grouped.get((consumer, state))
                                labels = {"consumer": consumer, "state": state}
                                self.depth.set(row.depth if row else 0, labels)
                                self.age.set(row.oldest_seconds if row else 0, labels)
                        self.collected.set(time())
                    except Exception:
                        logger.warning("delivery alert sampling failed")
                        # Immediately invalidate a failed collection, including if
                        # the SDK re-exports the previous per-state gauges.
                        self.collected.set(0)
                    await asyncio.sleep(INTERVAL)
            finally:
                await engine.dispose()
        finally:
            self.running.release()
