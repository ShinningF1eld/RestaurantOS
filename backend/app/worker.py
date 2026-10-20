"""Standalone event worker entrypoint: ``python -m app.worker``."""

from __future__ import annotations

import asyncio
import signal

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import configure_json_logging
from app.db.worker import create_worker_engine
from app.modules.events.worker.runtime import EventWorker, WorkerHooks


async def run_worker(
    stop: asyncio.Event,
    *,
    settings: Settings | None = None,
    hooks: WorkerHooks | None = None,
) -> None:
    """Run transport loops without starting FastAPI or applying migrations."""
    active_settings = settings or get_settings()
    configure_json_logging(level=active_settings.log_level)
    engine = create_worker_engine(active_settings)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        worker = EventWorker(active_settings, sessions, hooks=hooks)
        await worker.run(stop)
    finally:
        await engine.dispose()


async def _serve() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(_signum: int, _frame: object) -> None:
        loop.call_soon_threadsafe(stop.set)

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, request_stop)
    await run_worker(stop)


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
