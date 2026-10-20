"""Worker resources are bounded and live for exactly one invocation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app import worker
from app.db.worker import create_worker_engine


@pytest.mark.parametrize("concurrency", [1, 2, 16])
def test_worker_pool_is_bounded_without_connecting(unit_settings, concurrency):
    settings = unit_settings.model_copy(
        update={"environment": "test", "event_worker_relay_concurrency": concurrency}
    )
    engine = create_worker_engine(settings)
    assert isinstance(engine.pool, AsyncAdaptedQueuePool)
    assert engine.pool.size() == concurrency + 4
    assert engine.pool._max_overflow == 0
    assert engine.pool.timeout() == 5
    assert engine.pool._pre_ping
    assert engine.sync_engine.hide_parameters
    assert str(engine.url) == settings.database_url
    asyncio.run(engine.dispose())


@pytest.mark.parametrize("fails", [False, True])
def test_worker_disposes_its_own_engine_on_every_exit(
    monkeypatch, unit_settings, fails
):
    dispose = AsyncMock()
    engine = SimpleNamespace(dispose=dispose)
    created = []

    def factory(settings):
        assert settings is unit_settings
        created.append(engine)
        return engine

    class FakeWorker:
        def __init__(self, settings, sessions, *, hooks):
            assert settings is unit_settings
            assert sessions.kw["bind"] is engine
            assert sessions.kw["expire_on_commit"] is False

        async def run(self, stop):
            assert isinstance(stop, asyncio.Event)
            if fails:
                raise RuntimeError("worker startup failed")

    monkeypatch.setattr(worker, "create_worker_engine", factory)
    monkeypatch.setattr(worker, "EventWorker", FakeWorker)

    async def scenario():
        if fails:
            with pytest.raises(RuntimeError, match="worker startup failed"):
                await worker.run_worker(asyncio.Event(), settings=unit_settings)
        else:
            await worker.run_worker(asyncio.Event(), settings=unit_settings)

    asyncio.run(scenario())
    assert created == [engine]
    dispose.assert_awaited_once()
