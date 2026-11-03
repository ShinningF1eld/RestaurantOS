"""SDK measurements and Redis privacy/failure contracts without service IO."""

import asyncio
import time
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from redis.exceptions import ConnectionError, ResponseError, TimeoutError

from app.core import diagnostics, telemetry
from app.db.telemetry import failure_category
from app.redis.adapter import RedisAdapter, RedisFailure
from app.modules.events.worker.redis import WorkerRedisTransport, WorkerRedisFailure


@pytest.fixture
def measurements(monkeypatch):
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], shutdown_on_exit=False)
    sink = diagnostics.Diagnostics(provider, "api")
    for owner in (telemetry.lifecycle, telemetry.worker_lifecycle):
        monkeypatch.setattr(owner, "runtime", SimpleNamespace(diagnostics=sink))
    yield reader
    provider.shutdown()


def metrics(reader):
    data = reader.get_metrics_data()
    return {
        m.name: m.data.data_points
        for r in data.resource_metrics
        for s in r.scope_metrics
        for m in s.metrics
    }


@pytest.mark.parametrize(
    "transport,exception",
    [(RedisAdapter, RedisFailure), (WorkerRedisTransport, WorkerRedisFailure)],
)
@pytest.mark.parametrize(
    "failure,outcome",
    [
        (None, "success"),
        (TimeoutError("private"), "timeout"),
        (ConnectionError("private"), "connection"),
        (ResponseError("private"), "command"),
        (asyncio.CancelledError(), "cancelled"),
    ],
)
def test_redis_measurements(
    unit_settings, measurements, transport, exception, failure, outcome
):
    class Client:
        async def execute_command(self, *args):
            if failure is not None:
                raise failure
            return b"private-payload"

        async def aclose(self):
            pass

    async def run():
        adapter = transport(unit_settings, client_factory=lambda _: Client())
        await adapter.open()
        if failure is None:
            assert await adapter.execute("GET", "private-key") == b"private-payload"
        else:
            with pytest.raises(
                asyncio.CancelledError if outcome == "cancelled" else exception
            ):
                await adapter.execute("GET", "private-key")
        await adapter.close()

    asyncio.run(run())
    data = metrics(measurements)
    points = data["restaurantos.redis.operations"]
    assert len(points) == 1
    assert points[0].value == 1
    assert points[0].attributes == {
        "role": "api" if transport is RedisAdapter else "worker",
        "operation": "GET",
        "outcome": outcome,
    }
    duration = data["restaurantos.redis.duration"][0]
    assert duration.count == 1 and duration.sum >= 0
    assert "private" not in str(data)


def test_closed_and_unknown_commands(unit_settings, measurements):
    async def run():
        adapter = RedisAdapter(unit_settings)
        with pytest.raises(RedisFailure):
            await adapter.execute("private-command", "private-key")

    asyncio.run(run())
    point = metrics(measurements)["restaurantos.redis.operations"][0]
    assert point.attributes["outcome"] == "closed"
    assert point.attributes["operation"] == "OTHER"


def test_recording_failure_is_best_effort(monkeypatch):
    class Broken:
        def record(self, *args):
            raise RuntimeError("private")

    monkeypatch.setattr(
        telemetry.lifecycle, "runtime", SimpleNamespace(diagnostics=Broken())
    )
    diagnostics.record("sql.failures", 1, operation="OTHER", outcome="database")


def test_sql_failure_classification():
    class DatabaseError(Exception):
        sqlstate = "40001"

    assert failure_category(DatabaseError("private")) == "serialization"
    assert failure_category(asyncio.CancelledError()) == "cancelled"
    assert failure_category(RuntimeError("private")) == "database"


@pytest.mark.asyncio
@pytest.mark.parametrize("items", [False, True])
async def test_catalog_one_outcome_per_lookup(
    monkeypatch, fake_access, unit_principal, measurements, items
):
    from app.modules.catalog import service as catalog
    from app.modules.catalog.menu_cache import CatalogMenuCache

    fake_access(catalog)
    clock = [0.0]
    cache = CatalogMenuCache(monotonic=lambda: clock[0], wall_time=time.time)

    class Repository:
        def __init__(self, *args):
            pass

        async def list_menus_for_restaurant(self, restaurant):
            return []

        async def get_menu_by_id(self, menu):
            return SimpleNamespace(restaurant_id=1)

        async def list_menu_items_for_menu(self, menu):
            return []

    class Redis:
        value = None
        fail = False

        def namespace(self, *args):
            return "private-namespace"

        async def execute(self, *args):
            if self.fail:
                from app.redis.adapter import FailureKind

                raise RedisFailure(FailureKind.CONNECTION)
            if args[0] == "SET":
                self.value = args[2]
            return self.value if args[0] == "GET" else None

    async def available(self, models, **kwargs):
        return models

    monkeypatch.setattr(catalog, "CatalogRepository", Repository)
    monkeypatch.setattr(
        catalog.CatalogService, "_attach_menu_item_availability", available
    )
    redis = Redis()
    service = catalog.CatalogService(
        None, unit_principal, menu_cache=cache, redis=redis
    )
    lookup = service.list_menu_items if items else service.list_menus
    await lookup(1)  # absent
    await lookup(1)  # valid empty payload is still a hit
    redis.fail = True
    await lookup(1)  # attempted failure = miss
    await lookup(1)  # circuit skips lookup = bypass
    clock[0] = 6
    redis.fail = False
    await lookup(1)  # one recovery probe, valid payload
    # Revoked/foreign authorization must not count as a lookup.
    if not items:
        from app.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            await lookup(404)
    data = metrics(measurements)["restaurantos.catalog.cache.lookups"]
    assert {p.attributes["outcome"]: p.value for p in data} == {
        "hit": 2,
        "miss": 2,
        "bypass": 1,
    }
    assert {p.attributes["cache"] for p in data} == {"menu_items" if items else "menus"}
    assert "private" not in str(data)


@pytest.mark.parametrize("seconds", [0, 60.001])
def test_slow_threshold_is_bounded(unit_settings_kwargs, seconds):
    from pydantic import ValidationError
    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, **unit_settings_kwargs, monitoring_sql_slow_seconds=seconds
        )


@pytest.mark.asyncio
async def test_worker_pending_parser_and_safe_error_code(unit_settings, measurements):
    from app.modules.events.worker.redis import WorkerFailureKind

    class Client:
        async def xpending_range(self, *args):
            raise ResponseError("NOGROUP private-stream private-group")

        async def aclose(self):
            pass

    transport = WorkerRedisTransport(unit_settings, client_factory=lambda _: Client())
    await transport.open()
    with pytest.raises(WorkerRedisFailure) as captured:
        await transport.pending_range("private-stream", "private-group", "-", "+", 1)
    assert captured.value.kind == WorkerFailureKind.COMMAND
    assert captured.value.server_code == "NOGROUP"
    point = metrics(measurements)["restaurantos.redis.operations"][0]
    assert point.attributes == {
        "role": "worker",
        "operation": "XPENDING",
        "outcome": "command",
    }
    assert "private" not in str(point)
    await transport.close()
