"""Database resources owned by one worker invocation and its event loop."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings
from app.db.telemetry import ObservedWorkerPool, instrument_engine


def create_worker_engine(settings: Settings) -> AsyncEngine:
    # Three serial consumers, concurrent publication observations, and one
    # recovery scan. The relay's other DB work precedes publication. Unlike the
    # HTTP test adapter, a standalone worker never shares its pool across loops.
    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        hide_parameters=True,
        poolclass=ObservedWorkerPool,
        pool_size=3 + settings.event_worker_relay_concurrency + 1,
        max_overflow=0,
        pool_timeout=5,
        pool_pre_ping=True,
    )

    instrument_engine(
        engine.sync_engine,
        role="worker",
        slow_seconds=settings.monitoring_sql_slow_seconds,
        limit=3 + settings.event_worker_relay_concurrency + 1,
    )
    return engine
