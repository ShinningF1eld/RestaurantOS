"""Fresh-process pool proof. Only invoked with guarded test environment variables."""

import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from opentelemetry.sdk.metrics import MeterProvider  # noqa: E402
from opentelemetry.sdk.metrics.export import InMemoryMetricReader  # noqa: E402
from sqlalchemy import literal, select, text, table, column  # noqa: E402
from sqlalchemy.exc import DBAPIError, TimeoutError  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core import diagnostics, telemetry  # noqa: E402
from app.db.telemetry import instrument_engine  # noqa: E402


def snapshot(reader):
    data = reader.get_metrics_data()
    return {
        m.name: [
            {
                "attributes": dict(p.attributes),
                **(
                    {"value": p.value}
                    if hasattr(p, "value")
                    else {"count": p.count, "sum": p.sum}
                ),
            }
            for p in m.data.data_points
        ]
        for r in data.resource_metrics
        for s in r.scope_metrics
        for m in s.metrics
    }


async def probe(role):
    # Parent validation owns the database. Never accept an application URL alone.
    url = os.environ["TEST_DATABASE_URL"]
    assert url.startswith("postgresql+asyncpg://") and url.rsplit("/", 1)[1].endswith(
        "_test"
    )
    os.environ.update(DATABASE_URL=url, ENVIRONMENT="development")
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], shutdown_on_exit=False)
    owner = telemetry.worker_lifecycle if role == "worker" else telemetry.lifecycle
    owner.runtime = SimpleNamespace(
        diagnostics=diagnostics.Diagnostics(
            provider, role, 0 if role == "worker" else None
        )
    )
    settings = Settings(_env_file=None)
    if role == "worker":
        from app.db.worker import create_worker_engine

        engine = create_worker_engine(settings)
        capacity = 3 + settings.event_worker_relay_concurrency + 1
        overflow = 0
    else:
        from app.db.database import engine

        capacity, overflow = settings.database_pool_size, settings.database_max_overflow
    # Re-registration is a no-op, including event listeners.
    instrument_engine(engine.sync_engine, role=role, slow_seconds=0.001)
    acquired = []
    original = diagnostics.record
    entered = asyncio.Event()

    def observe(name, value, **attrs):
        original(name, value, **attrs)
        if name == "pool.acquiring" and value == 1:
            entered.set()

    import app.db.telemetry as hooks

    hooks.record = observe
    try:
        for _ in range(capacity + overflow):
            acquired.append(await engine.connect())
        saturated = snapshot(reader)
        assert saturated["restaurantos.pool.used"][0]["value"] == capacity + overflow
        assert saturated["restaurantos.pool.idle"][0]["value"] == 0
        assert saturated["restaurantos.pool.overflow"][0]["value"] == overflow
        assert saturated["restaurantos.pool.limit"][0]["value"] == capacity + overflow
        entered.clear()
        task = asyncio.create_task(engine.connect().__aenter__())
        await asyncio.wait_for(entered.wait(), 2)
        # The first task yielded inside the real full queue's connect call.
        assert not task.done()
        assert snapshot(reader)["restaurantos.pool.acquiring"][0]["value"] == 1
        with_timeout = False
        try:
            await asyncio.wait_for(task, settings.database_pool_timeout_seconds + 7)
        except TimeoutError:
            with_timeout = True
        assert with_timeout
        entered.clear()
        task = asyncio.create_task(engine.connect().__aenter__())
        await asyncio.wait_for(entered.wait(), 2)
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await acquired.pop().close()
        recovered = await engine.connect()
        await recovered.execute(select(literal("SQL_PRIVATE_CANARY")))
        await recovered.rollback()  # ordinary read teardown is not a failure
        assert "restaurantos.transaction.failures" not in snapshot(reader)
        await recovered.execute(text("SELECT pg_sleep(0.02)"))
        await recovered.rollback()
        for statement in ("SELECT 1/0 /* SQL_PRIVATE_CANARY */", "SELECT 1"):
            try:
                await recovered.execute(text(statement))
            except DBAPIError:
                pass
            else:
                raise AssertionError("Expected failed or aborted transaction")
        assert (
            sum(
                p["value"]
                for p in snapshot(reader)["restaurantos.transaction.failures"]
            )
            == 1
        )
        await recovered.rollback()
        async with recovered.begin():
            await recovered.execute(
                text(
                    "CREATE TEMP TABLE diagnostics_values (value integer UNIQUE DEFERRABLE INITIALLY DEFERRED)"
                )
            )
            values = table("diagnostics_values", column("value"))
            await recovered.execute(values.insert().values(value=1))
            await recovered.execute(values.update().values(value=2))
            await recovered.execute(values.delete())
        try:
            async with recovered.begin():
                await recovered.execute(values.insert().values(value=1))
                await recovered.execute(values.insert().values(value=1))
        except DBAPIError:
            pass  # deferred constraint fails at COMMIT, without a cursor timing
        else:
            raise AssertionError("Expected deferred-constraint commit failure")
        failures = snapshot(reader)["restaurantos.transaction.failures"]
        assert any(
            p["attributes"]["outcome"] == "constraint" and p["value"] == 1
            for p in failures
        )
        async with recovered.begin():
            await recovered.execute(select(literal(1)))
        # Server cancellation reaches handle_error and clears its per-execution timer.
        executing = asyncio.Event()
        from sqlalchemy import event

        def executing_query(*args):
            executing.set()

        event.listen(engine.sync_engine, "before_cursor_execute", executing_query)
        task = asyncio.create_task(recovered.execute(text("SELECT pg_sleep(30)")))
        await executing.wait()
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await recovered.rollback()
        await recovered.close()
        for connection in acquired:
            await connection.close()
        acquired.clear()
        result = snapshot(reader)
        assert result["restaurantos.pool.used"][0]["value"] == 0
        assert result["restaurantos.pool.acquiring"][0]["value"] == 0
        assert sum(p["value"] for p in result["restaurantos.transaction.failures"]) >= 1
        assert "SQL_PRIVATE_CANARY" not in json.dumps(result)
        assert all(
            p["attributes"]["role"] == role
            for points in result.values()
            for p in points
        )
        print(json.dumps(result))
    finally:
        for connection in acquired:
            await connection.close()
        await engine.dispose()
        owner.runtime = None
        provider.shutdown()


if __name__ == "__main__":
    asyncio.run(probe(sys.argv[1]))
