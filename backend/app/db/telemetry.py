"""SQLAlchemy 2 engine events and a transparent async pool connect boundary."""

import asyncio
from functools import wraps
from time import monotonic
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.core.diagnostics import record, register_engine


class ObservedAsyncPool(AsyncAdaptedQueuePool):
    """Measure public connect(), including waiting/connect/pre-ping, unchanged.

    Acquiring is NOT the queue's waiter count: SQLAlchemy has no public waiter
    observation API. Never infer waiters by subtracting checked-out capacity.
    """

    telemetry_role = "api"

    def connect(self) -> Any:
        started = monotonic()
        role = self.telemetry_role
        record("pool.acquiring", 1, role=role)
        outcome = "success"
        try:
            return super().connect()
        except BaseException as error:
            outcome = (
                "timeout"
                if isinstance(error, PoolTimeout)
                else "cancelled"
                if isinstance(error, asyncio.CancelledError)
                else "connection"
            )
            record("pool.acquire.failures", 1, role=role, outcome=outcome)
            raise
        finally:
            record("pool.acquiring", -1, role=role)
            record(
                "pool.acquire.duration",
                monotonic() - started,
                role=role,
                outcome=outcome,
            )


class ObservedWorkerPool(ObservedAsyncPool):
    telemetry_role = "worker"


def failure_category(error: BaseException | None) -> str:
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    code = getattr(error, "sqlstate", None) or getattr(
        getattr(error, "orig", None), "sqlstate", None
    )
    if isinstance(code, str):
        if code in {"40P01", "40001", "55P03"}:
            return {"40P01": "deadlock", "40001": "serialization", "55P03": "lock"}[
                code
            ]
        return {
            "40": "transaction",
            "23": "constraint",
            "08": "connection",
            "57": "interrupted",
        }.get(code[:2], "database")
    return "database"


def instrument_engine(
    engine: Engine, *, role: str, slow_seconds: float, limit: int | None = None
) -> None:
    if getattr(engine, "_restaurantos_instrumented", False):
        return
    engine._restaurantos_instrumented = True  # type: ignore[attr-defined]
    register_engine(engine, role, limit)

    def finish(context: Any, outcome: str) -> None:
        measurement = getattr(context, "_restaurantos_timing", None)
        if measurement is None:
            return
        del context._restaurantos_timing
        started, operation = measurement
        elapsed = monotonic() - started
        record("sql.duration", elapsed, role=role, operation=operation, outcome=outcome)
        if elapsed >= slow_seconds:
            record("sql.slow", 1, role=role, operation=operation, outcome=outcome)
        if outcome != "success":
            record("sql.failures", 1, role=role, operation=operation, outcome=outcome)

    def before(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        many: bool,
    ) -> None:
        # Compiled expression flags only. Text/driver SQL and expressions
        # without a recognized flag are OTHER; never parse raw SQL.
        compiled = getattr(context, "compiled", None)
        expression = getattr(compiled, "statement", None)
        operation = "OTHER"
        for flag, category in (
            ("is_select", "SELECT"),
            ("is_insert", "INSERT"),
            ("is_update", "UPDATE"),
            ("is_delete", "DELETE"),
        ):
            if getattr(expression, flag, False):
                operation = category
                break
        context._restaurantos_timing = (monotonic(), operation)

    def after(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        many: bool,
    ) -> None:
        finish(context, "success")

    def error(context: Any) -> None:
        outcome = failure_category(context.original_exception)
        finish(context.execution_context, outcome)
        conn = context.connection
        if (
            conn is not None
            and not conn.invalidated
            and conn.in_transaction()
            and not conn.info.get("restaurantos_transaction_failed")
        ):
            conn.info["restaurantos_transaction_failed"] = True
            record("transaction.failures", 1, role=role, outcome=outcome)

    def reset(conn: Any) -> None:
        conn.info.pop("restaurantos_transaction_failed", None)

    def safe(listener: Any) -> Any:
        @wraps(listener)
        def observe(*args: Any, **kwargs: Any) -> None:
            try:
                listener(*args, **kwargs)
            except Exception:
                pass

        return observe

    # Events execute on AsyncEngine.sync_engine in SQLAlchemy's greenlet bridge.
    event.listen(engine, "before_cursor_execute", safe(before))
    event.listen(engine, "after_cursor_execute", safe(after))
    event.listen(engine, "handle_error", safe(error))
    # Commit events run before the driver commit. Keep the failure sentinel until
    # rollback/next begin so a later failed commit cannot count the same transaction twice.
    for name in ("begin", "rollback"):
        event.listen(engine, name, safe(reset))
