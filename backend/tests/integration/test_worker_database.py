"""Real PostgreSQL worker connection reuse, invalidation and disposal."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.db.worker import create_worker_engine
from conftest import engine as observer


@pytest.mark.parametrize("disconnect", [False, True])
def test_worker_reuses_or_reconnects_and_disposes_its_pool(disconnect):
    async def invocation():
        engine = create_worker_engine(get_settings())
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        pids = []
        try:
            async with sessions() as session, session.begin():
                first = await session.scalar(text("SELECT pg_backend_pid()"))
                pids.append(first)
                await session.execute(text("SET LOCAL app.worker_pool_test = 'first'"))
            if disconnect:
                with observer.begin() as connection:
                    assert connection.scalar(
                        text("SELECT pg_terminate_backend(:pid, 5000)"), {"pid": first}
                    )
            async with sessions() as session, session.begin():
                second = await session.scalar(text("SELECT pg_backend_pid()"))
                pids.append(second)
                assert (second != first) is disconnect
                assert await session.scalar(
                    text("SELECT current_setting('app.worker_pool_test', true)")
                ) in (None, "")
        finally:
            await engine.dispose()
        with observer.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(:pids)"
                    ),
                    {"pids": pids},
                )
                == 0
            )

    # Invocations get independent pools even if a test launches another loop.
    asyncio.run(invocation())
    asyncio.run(invocation())
