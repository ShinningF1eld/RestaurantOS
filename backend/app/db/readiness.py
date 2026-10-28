"""Read-only database readiness with one total acquisition/query/cleanup budget."""

import asyncio
from contextlib import suppress
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


async def database_ready(engine: AsyncEngine, *, timeout_seconds: float = 2) -> bool:
    driver: Any = None
    lease: AsyncConnection | None = None

    async def probe() -> bool:
        nonlocal driver, lease
        async with engine.connect() as connection:
            lease = connection
            driver = (await connection.get_raw_connection()).driver_connection
            return (await connection.execute(text("SELECT 1"))).scalar_one() == 1

    task = asyncio.create_task(probe())
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout_seconds)
        return await task if done else False
    except (SQLAlchemyError, OSError):
        # Callers receive no connection details or exception text.
        return False
    finally:
        if not task.done():
            # asyncpg's graceful cancellation/close can outlive our deadline
            # when PostgreSQL is suspended. Terminate this probe's connection
            # before cancellation; SQLAlchemy discards it instead of reusing it.
            # A context's close can return the connection before the probe task
            # resumes. Never terminate a connection already lent to another user.
            if driver is not None and lease is not None and not lease.closed:
                driver.terminate()
            task.cancel()
            with suppress(asyncio.CancelledError, SQLAlchemyError, OSError):
                await task
