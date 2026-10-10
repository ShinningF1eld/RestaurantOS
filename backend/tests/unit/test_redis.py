import asyncio
import traceback
from time import monotonic

import pytest
from pydantic import ValidationError
from redis.exceptions import (
    ConnectionError,
    InvalidResponse,
    ResponseError,
    TimeoutError as RedisTimeout,
)

from app.core.config import Settings
from app.redis.adapter import FailureKind, RedisAdapter, RedisFailure, create_client


class FakeClient:
    def __init__(self, error=None):
        self.error = error
        self.calls = []
        self.closes = 0

    async def execute_command(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return None

    async def aclose(self):
        self.closes += 1


@pytest.mark.parametrize("budget", [0, -1, 101, "bad"])
def test_invalid_budget(unit_settings_kwargs, budget):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, **unit_settings_kwargs, redis_operation_budget_ms=budget
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://host",
        "redis://",
        "redis://host:bad",
        "redis://host/-1",
        "redis://host/0?socket_timeout=99",
    ],
)
def test_invalid_url_safe(unit_settings_kwargs, url):
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, **unit_settings_kwargs, redis_url=url)
    assert url not in str(caught.value)


@pytest.mark.parametrize(
    "fields",
    [
        {"redis_max_connections": 0},
        {"redis_max_connections": 1001},
        {"redis_test_namespace": "bad:namespace"},
    ],
)
def test_invalid_pool_and_namespace_settings(unit_settings_kwargs, fields):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **unit_settings_kwargs, **fields)


def test_invalid_credential_url_diagnostics_are_redacted(unit_settings_kwargs):
    url = "redis://private-user:private-password@host/0?retry_on_timeout=true"  # pragma: allowlist secret
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, **unit_settings_kwargs, redis_url=url)
    assert "private-user" not in str(caught.value)
    assert "private-password" not in str(caught.value)


def test_settings_secrets_and_driver_options(unit_settings_kwargs):
    url = (
        "rediss://test-user:private-value@localhost:6380/2"  # pragma: allowlist secret
    )
    settings = Settings(_env_file=None, **unit_settings_kwargs, redis_url=url)
    assert url not in repr(settings)
    assert "private-value" not in settings.model_dump_json()
    client = create_client(settings)
    options = client.connection_pool.connection_kwargs
    assert options["socket_timeout"] == options["socket_connect_timeout"] == 0.1
    assert options["retry"].get_retries() == 0
    assert options["retry_on_error"] == []
    assert options["decode_responses"] is False


@pytest.mark.asyncio
async def test_lifecycle_reuses_closes_and_reopens(unit_settings):
    clients = []

    def factory(settings):
        client = FakeClient()
        clients.append(client)
        return client

    adapter = RedisAdapter(unit_settings, client_factory=factory)
    with pytest.raises(RedisFailure, match="closed"):
        await adapter.execute("GET", "key")
    await adapter.open()
    await adapter.open()
    assert await adapter.execute("GET", "key") is None
    await adapter.execute("PING")
    assert len(clients) == 1 and len(clients[0].calls) == 2
    await adapter.close()
    await adapter.close()
    assert clients[0].closes == 1
    await adapter.open()
    assert len(clients) == 2
    await adapter.close()


@pytest.mark.parametrize(
    "error,kind",
    [
        (ConnectionError, FailureKind.CONNECTION),
        (InvalidResponse, FailureKind.CONNECTION),
        (OSError, FailureKind.CONNECTION),
        (RedisTimeout, FailureKind.TIMEOUT),
        (ResponseError, FailureKind.COMMAND),
    ],
)
@pytest.mark.asyncio
async def test_safe_classification(unit_settings, error, kind, caplog):
    secret = "redis://private-user:private-password@host/0"  # pragma: allowlist secret
    client = FakeClient(error(secret))
    adapter = RedisAdapter(unit_settings, client_factory=lambda _: client)
    await adapter.open()
    with pytest.raises(RedisFailure) as caught:
        await adapter.execute("GET", "sensitive-key")
    assert caught.value.kind == kind
    assert caught.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(caught.value))
    assert not caplog.records
    await adapter.close()


@pytest.mark.asyncio
async def test_single_total_deadline_including_acquisition_and_reply(unit_settings):
    cancelled = asyncio.Event()

    class SlowClient(FakeClient):
        async def execute_command(self, *args):
            try:
                # Model acquisition/connect taking most of the single budget,
                # followed by an indefinitely stalled reply.
                await asyncio.sleep(0.065)
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    adapter = RedisAdapter(unit_settings, client_factory=lambda _: SlowClient())
    await adapter.open()
    start = monotonic()
    with pytest.raises(RedisFailure) as caught:
        await adapter.execute("PING")
    elapsed = monotonic() - start
    assert caught.value.kind == FailureKind.TIMEOUT
    assert cancelled.is_set()
    # Small scheduler tolerance, but far below additive connect+read budgets.
    assert 0.09 <= elapsed < 0.15
    await adapter.close()


@pytest.mark.asyncio
async def test_cancellation_is_not_health_failure(unit_settings):
    adapter = RedisAdapter(
        unit_settings, client_factory=lambda _: FakeClient(asyncio.CancelledError())
    )
    await adapter.open()
    with pytest.raises(asyncio.CancelledError):
        await adapter.execute("PING")
    await adapter.close()


@pytest.mark.asyncio
async def test_close_is_bounded_and_clears_lifecycle_reference(unit_settings):
    class SlowClose(FakeClient):
        async def aclose(self):
            await asyncio.Event().wait()

    adapter = RedisAdapter(unit_settings, client_factory=lambda _: SlowClose())
    await adapter.open()
    with pytest.raises(RedisFailure) as caught:
        await adapter.close()
    assert caught.value.kind == FailureKind.TIMEOUT
    with pytest.raises(RedisFailure, match="closed"):
        await adapter.execute("PING")


def test_namespace_separates_environment_use_case_version_and_run(unit_settings_kwargs):
    def adapter(environment, run="owned"):
        return RedisAdapter(
            Settings(
                _env_file=None,
                **unit_settings_kwargs,
                environment=environment,
                redis_test_namespace=run,
            )
        )

    assert (
        adapter("development").namespace("catalog", 1)
        == "restaurantos:development:catalog:v1:"
    )
    assert adapter("test").namespace("auth", 2) == "restaurantos:test:owned:auth:v2:"
    assert adapter("test", "other").namespace("auth", 2) != adapter("test").namespace(
        "auth", 2
    )
    with pytest.raises(ValueError):
        adapter("test").namespace("email@example.test", 1)


def test_runner_requires_explicit_test_ports_and_overrides_ambient(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    from test_support.redis_environment import redis_environment

    with pytest.raises(ValueError):
        redis_environment({"REDIS_URL": "redis://developer:6379/0"})
    env = redis_environment(
        {
            "TEST_REDIS_HOST": "127.0.0.1",
            "TEST_REDIS_PORT": "34567",
            "REDIS_URL": "redis://developer:6379/0",
        }
    )
    assert env["REDIS_URL"] == "redis://127.0.0.1:34567/0"
    assert env["ENVIRONMENT"] == "test"
    assert env["REDIS_TEST_NAMESPACE"] != redis_environment(env)["REDIS_TEST_NAMESPACE"]
