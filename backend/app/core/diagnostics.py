"""Bounded infrastructure metrics on the existing optional SDK lifecycle.

No exporter, global provider, SQL text, Redis arguments or business IDs live here.
Recording and callbacks are best effort and never perform network IO.
"""

from collections.abc import Iterable
from typing import Any
from threading import Lock
from weakref import WeakKeyDictionary

from opentelemetry.metrics import MeterProvider, Observation
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

_engines: WeakKeyDictionary[Engine, tuple[str, int | None]] = WeakKeyDictionary()
_engines_lock = Lock()


def register_engine(engine: Engine, role: str, limit: int | None) -> None:
    with _engines_lock:
        _engines[engine] = (role, limit)


def pool_samples(role: str, field: str) -> Iterable[Observation]:
    with _engines_lock:
        engines = list(_engines.items())
    for engine, (owner, limit) in engines:
        if owner != role or not isinstance(engine.pool, QueuePool):
            continue
        pool = engine.pool
        if field == "limit":
            if limit is not None:
                yield Observation(limit, {"role": role})
            continue
        try:
            value = {
                "capacity": pool.size,
                "idle": pool.checkedin,
                "used": pool.checkedout,
                "overflow": lambda: max(0, pool.overflow()),
            }[field]()
            yield Observation(value, {"role": role})
        except Exception:
            continue


class Diagnostics:
    def __init__(self, provider: MeterProvider, role: str) -> None:
        meter = provider.get_meter("restaurantos.infrastructure", "1")
        self.instruments: dict[str, Any] = {}
        for name in ("sql.duration", "pool.acquire.duration", "redis.duration"):
            self.instruments[name] = meter.create_histogram(
                "restaurantos." + name, unit="s"
            )
        for name in (
            "sql.slow",
            "sql.failures",
            "transaction.failures",
            "pool.acquire.failures",
            "redis.operations",
            "catalog.cache.lookups",
        ):
            self.instruments[name] = meter.create_counter(
                "restaurantos." + name, unit="1"
            )

        def callback(field: str) -> Any:
            def observe(options: Any) -> Iterable[Observation]:
                return pool_samples(role, field)

            return observe

        for field in ("capacity", "limit", "idle", "used", "overflow"):
            meter.create_observable_gauge(
                "restaurantos.pool." + field,
                callbacks=[callback(field)],
                unit="{connection}",
            )
        self.instruments["pool.acquiring"] = meter.create_up_down_counter(
            "restaurantos.pool.acquiring", unit="{connection}"
        )

    def record(self, name: str, value: float, attributes: dict[str, str]) -> None:
        instrument = self.instruments[name]
        if name.endswith("duration"):
            instrument.record(value, attributes)
        else:
            instrument.add(value, attributes)


def record(name: str, value: float, *, role: str = "api", **attributes: str) -> None:
    try:
        from app.core.telemetry import lifecycle, worker_lifecycle

        runtime = (worker_lifecycle if role == "worker" else lifecycle).runtime
        if runtime is not None:
            runtime.diagnostics.record(name, value, {"role": role, **attributes})
    except Exception:
        # Monitoring must never change a command result, rollback or cancellation.
        pass


def redis_operation(arguments: tuple[object, ...]) -> str:
    # Never stringify arbitrary objects or export an unrecognized command.
    command = arguments[0] if arguments else None
    if not isinstance(command, str) or len(command) > 16:
        return "OTHER"
    command = command.upper()
    return (
        command
        if command
        in {
            "GET",
            "SET",
            "DEL",
            "EVAL",
            "PING",
            "XADD",
            "XREADGROUP",
            "XACK",
            "XPENDING",
            "XCLAIM",
            "XAUTOCLAIM",
            "XGROUP",
            "XLEN",
            "XRANGE",
        }
        else "OTHER"
    )
