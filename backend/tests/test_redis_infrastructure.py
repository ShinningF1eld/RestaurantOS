import asyncio
import socket
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import get_settings
from app.main import app
from app.redis.adapter import FailureKind, RedisAdapter, RedisFailure


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.asyncio
async def test_real_redis_owned_cleanup_after_success_and_failure(fail):
    settings = get_settings()
    assert settings.environment == "test"
    adapter = RedisAdapter(settings)
    await adapter.open()
    prefix = adapter.namespace("infrastructure", 1) + uuid4().hex
    key, other = prefix + ":owned", prefix + ":sentinel"
    try:
        assert await adapter.execute("PING") is True
        assert await adapter.execute("SET", other, "unrelated", "EX", 30) is True
        try:
            assert (
                await adapter.execute("SET", key, "{malformed-json", "EX", 30) is True
            )
            # Payload validation is intentionally above the adapter.
            assert await adapter.execute("GET", key) == b"{malformed-json"
            if fail:
                raise RuntimeError("Injected failure after owned Redis write")
        except RuntimeError:
            if not fail:
                raise
        finally:
            await adapter.execute("DEL", key)
        assert await adapter.execute("GET", key) is None
        assert await adapter.execute("GET", other) == b"unrelated"
    finally:
        try:
            await adapter.execute("DEL", key, other)
        finally:
            await adapter.close()


def test_startup_and_liveness_with_unavailable_redis(monkeypatch):
    # Reserve a random non-listening port so there is no fixed test-port collision.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        settings = get_settings().model_copy(
            update={
                "redis_url": SecretStr(
                    f"redis://127.0.0.1:{reserved.getsockname()[1]}/0"
                )
            }
        )
        monkeypatch.setattr("app.main.settings", settings)
        with TestClient(app) as client:
            adapter = app.state.redis
            assert client.get("/health").json() == {
                "status": "ok",
                "service": "restaurantos-api",
            }
            # Run in the same event loop that owns the application client.
            with pytest.raises(RedisFailure) as caught:
                client.portal.call(adapter.execute, "PING")
            # Windows may leave a connect to a bound non-listening port pending
            # until the outer deadline rather than immediately refusing it.
            assert caught.value.kind in {FailureKind.CONNECTION, FailureKind.TIMEOUT}
            assert client.get("/health").status_code == 200
            assert app.state.redis is adapter
        assert not hasattr(app.state, "redis")


def test_nested_lifecycle_owns_and_restores_adapter():
    with TestClient(app):
        outer = app.state.redis
        with TestClient(app) as inner:
            adapter = app.state.redis
            assert adapter is not outer
            assert inner.portal.call(adapter.execute, "PING") is True
            assert inner.portal.call(adapter.execute, "PING") is True
            assert app.state.redis is adapter
        assert app.state.redis is outer
    assert not hasattr(app.state, "redis")


def test_overlapping_lifespans_close_out_of_order():
    first = TestClient(app)
    second = TestClient(app)
    first.__enter__()
    try:
        second.__enter__()
        try:
            survivor = app.state.redis
            first.__exit__(None, None, None)
            assert app.state.redis is survivor
            assert second.portal.call(survivor.execute, "PING") is True
        finally:
            second.__exit__(None, None, None)
    finally:
        first.__exit__(None, None, None)
    assert not hasattr(app.state, "redis")
    assert app.state.redis_lifespans == []


@pytest.mark.asyncio
async def test_real_stalled_transport_total_deadline():
    accepted = asyncio.Event()
    released = asyncio.Event()
    finished = asyncio.Event()

    async def stall(reader, writer):
        accepted.set()
        try:
            await released.wait()
        finally:
            writer.close()
            await writer.wait_closed()
            finished.set()

    server = await asyncio.start_server(stall, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    settings = get_settings().model_copy(
        update={"redis_url": SecretStr(f"redis://127.0.0.1:{port}/0")}
    )
    adapter = RedisAdapter(settings)
    await adapter.open()
    try:
        start = asyncio.get_running_loop().time()
        with pytest.raises(RedisFailure) as caught:
            await adapter.execute("PING")
        assert caught.value.kind == FailureKind.TIMEOUT
        assert accepted.is_set()
        assert asyncio.get_running_loop().time() - start < 0.15
    finally:
        released.set()
        server.close()
        await server.wait_closed()
        await adapter.close()
        await asyncio.wait_for(finished.wait(), 1)
