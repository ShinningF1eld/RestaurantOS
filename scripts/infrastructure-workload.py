"""Synthetic producer for check-infrastructure-observability.py only."""

import asyncio
import os
import sys

from app.core.config import Settings
from app.core.telemetry import lifecycle, worker_lifecycle
from app.modules.events.worker.redis import WorkerRedisFailure, WorkerRedisTransport
from app.redis.adapter import RedisAdapter, RedisFailure
from sqlalchemy import literal, select, text
from sqlalchemy.exc import DBAPIError, TimeoutError


async def main(role):
    url = os.environ["TEST_DATABASE_URL"]
    assert url.startswith("postgresql+asyncpg://") and url.rsplit("/", 1)[1].endswith(
        "_test"
    )
    os.environ["ENVIRONMENT"] = "development"
    settings = Settings(_env_file=None)
    owner = worker_lifecycle if role == "worker" else lifecycle
    runtime = owner.acquire(settings)
    assert runtime is not None
    if role == "worker":
        from app.db.worker import create_worker_engine

        engine = create_worker_engine(settings)
        capacity = 3 + settings.event_worker_relay_concurrency + 1
    else:
        from app.db.database import engine

        capacity = settings.database_pool_size + settings.database_max_overflow
    adapter = (
        WorkerRedisTransport(settings) if role == "worker" else RedisAdapter(settings)
    )
    quick = os.environ.get("INFRASTRUCTURE_QUICK") == "1"

    async def flush():
        try:
            await asyncio.to_thread(runtime.metrics.force_flush, 2000)
        except Exception:
            if os.environ.get("INFRASTRUCTURE_COLLECTOR_ABSENT") != "1":
                raise
            # Explicit test-only flush may fail when the destination is absent.
            # Business code only records/enqueues and never calls force_flush.

    held = []
    try:
        await adapter.open()
        await adapter.execute(
            "SET", "INFRA_PRIVATE_CANARY", "INFRA_PRIVATE_CANARY", "EX", 60
        )
        await adapter.execute("GET", "INFRA_PRIVATE_CANARY")
        try:
            await adapter.execute("UNKNOWN_INFRA_PRIVATE_CANARY")
        except (RedisFailure, WorkerRedisFailure):
            pass
        for _ in range(1 if quick else capacity):
            held.append(await engine.connect())
        if not quick:
            entered = asyncio.Event()

            async def acquire():
                entered.set()
                return await engine.connect()

            pending = asyncio.create_task(acquire())
            await asyncio.wait_for(entered.wait(), 2)
            assert not pending.done()
            # acquire() has yielded inside the real full pool; export its pending
            # acquisition before awaiting the unchanged pool timeout.
            await flush()
            try:
                await pending
            except TimeoutError:
                pass
            else:
                raise AssertionError("Expected full pool timeout")
        connection = held.pop()
        await connection.execute(select(literal("INFRA_PRIVATE_CANARY")))
        await connection.rollback()
        await connection.execute(
            text("SELECT pg_sleep(0.6) /* INFRA_PRIVATE_CANARY */")
        )
        await connection.rollback()
        try:
            async with connection.begin():
                await connection.execute(text("SELECT 1/0 /* INFRA_PRIVATE_CANARY */"))
        except DBAPIError:
            pass
        async with connection.begin():
            await connection.execute(select(literal(1)))
        await connection.close()
        for connection in held:
            await connection.close()
        held.clear()
        await flush()
    finally:
        for connection in held:
            await connection.close()
        await adapter.close()
        await engine.dispose()
        await asyncio.to_thread(
            owner.release(runtime).wait, settings.monitoring_shutdown_seconds
        )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
