"""Real PostgreSQL success, pool contention and unreachable-service readiness."""

import asyncio
import os
import socket
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.readiness import database_ready
from app.main import app


def test_readiness_bounds_real_pool_checkout_and_recovers():
    async def scenario():
        engine = create_async_engine(
            os.environ["TEST_DATABASE_URL"],
            pool_size=1,
            max_overflow=0,
            pool_timeout=30,
        )
        try:
            async with engine.connect():
                started = time.monotonic()
                assert not await database_ready(engine, timeout_seconds=0.05)
                assert time.monotonic() - started < 1
                assert engine.pool.checkedout() == 1
            assert await database_ready(engine)
            assert engine.pool.checkedout() == 0
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_unreachable_database_returns_generic_503_without_breaking_liveness(
    monkeypatch,
):
    import app.main as application

    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        url = make_url(os.environ["TEST_DATABASE_URL"]).set(
            host="127.0.0.1", port=unavailable.getsockname()[1]
        )
        engine = create_async_engine(url, poolclass=NullPool)
        monkeypatch.setattr(application, "database_engine", engine)
        try:
            with TestClient(app) as client:
                started = time.monotonic()
                response = client.get("/ready")
                assert time.monotonic() - started < 3
                assert response.status_code == 503
                assert response.json() == {"status": "unavailable"}
                assert response.headers["cache-control"] == "no-store"
                assert client.get("/health").status_code == 200
        finally:
            asyncio.run(engine.dispose())


def test_cancelled_readiness_releases_pending_pool_checkout():
    async def scenario():
        engine = create_async_engine(
            os.environ["TEST_DATABASE_URL"], pool_size=1, max_overflow=0
        )
        try:
            async with engine.connect():
                probe = asyncio.create_task(database_ready(engine))
                await asyncio.sleep(0)
                probe.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await probe
                assert engine.pool.checkedout() == 1
            assert await database_ready(engine)
            assert engine.pool.checkedout() == 0
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_timeout_after_pool_return_does_not_terminate_another_borrower(monkeypatch):
    async def scenario():
        engine = create_async_engine(
            os.environ["TEST_DATABASE_URL"], pool_size=1, max_overflow=0
        )
        returned = asyncio.Event()
        release = asyncio.Event()
        original_exit = AsyncConnection.__aexit__
        probe_driver = None

        async def pause_after_return(connection, *arguments):
            nonlocal probe_driver
            first_return = not returned.is_set()
            if first_return:
                probe_driver = (await connection.get_raw_connection()).driver_connection
            await original_exit(connection, *arguments)
            if first_return:
                returned.set()
                await release.wait()

        monkeypatch.setattr(AsyncConnection, "__aexit__", pause_after_return)
        try:
            probe = asyncio.create_task(database_ready(engine))
            await asyncio.wait_for(returned.wait(), 3)
            # The exact same real pooled connection is now leased elsewhere
            # while the probe is held after return, before its task completes.
            async with engine.connect() as borrower:
                assert (
                    await borrower.get_raw_connection()
                ).driver_connection is probe_driver
                assert not await probe
                assert (await borrower.execute(text("SELECT 42"))).scalar_one() == 42
                release.set()
            assert engine.pool.checkedout() == 0
        finally:
            release.set()
            await engine.dispose()

    asyncio.run(scenario())
