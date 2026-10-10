"""Prepare shared-mode test connections before overlapping quota operations."""

import asyncio

from app.redis.adapter import RedisFailure


async def warm_redis(adapter, connections=8):
    # Only PING is retried here, before any auth admission. Actual limiter
    # operations retain the production deadline and are never blindly replayed.
    for _ in range(10):
        results = await asyncio.gather(
            *(adapter.execute("PING") for _ in range(connections)),
            return_exceptions=True,
        )
        if all(result is True for result in results):
            return
        for result in results:
            if isinstance(result, BaseException) and not isinstance(
                result, RedisFailure
            ):
                raise result
    raise AssertionError("Isolated Redis connections did not become ready")
