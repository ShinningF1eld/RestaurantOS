"""Real PostgreSQL analytics effects, watermarks and deterministic lock overlap."""

import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.database import AsyncSessionLocal
from app.modules.analytics.service import AnalyticsProjectionService
from app.modules.analytics.repo.models import OrderContribution
from app.modules.events.domain.contracts import (
    OrderCompletedEvent,
    OrderCompletedPayload,
    OrderDeletedEvent,
    OrderDeletedPayload,
)
from app.modules.events.execution import ConsumerExecutionService, ExecutionHooks
from app.modules.events.domain.retries import RetryPolicy
from app.modules.events.operator import EventOperatorService
from app.modules.events.repo.models import EventDelivery, EventReceipt
from app.modules.events.service import append_event
from app.modules.orders.repo.models import Order
from conftest import engine
from test_event_worker import (
    BACKEND,
    create_scope,
    start_process,
    kill_process,
    process_phase,
    wait_for,
    worker_settings,
    delivery_rows,
)
from test_event_execution import reference


CREATED = datetime(2026, 10, 1, 23, 45)


def event(
    scope, order_id, revision=4, *, deleted=False, total="12.34", created=CREATED
):
    common = dict(
        organization_id=scope[0],
        restaurant_id=scope[1],
        aggregate_id=str(order_id),
        aggregate_revision=revision,
        occurred_at=datetime.now(UTC),
        correlation_id="analytics-test",
    )
    payload = dict(order_id=order_id, total=total, created_at=created)
    value = (
        OrderDeletedEvent(
            **common, payload=OrderDeletedPayload(**payload, prior_status="COMPLETED")
        )
        if deleted
        else OrderCompletedEvent(**common, payload=OrderCompletedPayload(**payload))
    )

    async def append():
        async with AsyncSessionLocal() as session, session.begin():
            await append_event(session, value)

    asyncio.run(append())
    return value


async def execute(value, *, hooks=ExecutionHooks(), max_attempts=8):
    return await ConsumerExecutionService(
        AsyncSessionLocal, hooks=hooks, policy=RetryPolicy(max_attempts=max_attempts)
    ).execute(
        event_id=value.event_id,
        consumer="analytics",
        reference=reference(value),
        worker_id="analytics-test",
    )


def live_order(
    scope, order_id=1, *, revision=4, total="12.34", status="COMPLETED", created=CREATED
):
    with Session(engine) as session, session.begin():
        session.add(
            Order(
                order_id=order_id,
                restaurant_id=scope[1],
                revision=revision,
                total=Decimal(total),
                subtotal=Decimal(total),
                status=status,
                created_at=created,
            )
        )


def inspect(scope):
    return asyncio.run(AnalyticsProjectionService(AsyncSessionLocal).inspect(*scope))


@pytest.mark.parametrize("deleted_first", [True, False])
def test_completion_deletion_permutations_duplicates_and_reconciliation(deleted_first):
    scope = create_scope()
    complete = event(scope, 1)
    deleted = event(scope, 1, 5, deleted=True)
    for value in [deleted, complete] if deleted_first else [complete, deleted]:
        assert asyncio.run(execute(value)).acknowledge
        assert asyncio.run(execute(value)).outcome == "durable_receipt_acknowledged"
    # Another event UUID at the old revision is also harmless.
    assert asyncio.run(execute(event(scope, 1))).acknowledge
    output = inspect(scope)
    assert output["orders"][0]["state"] == "deleted"
    assert output["orders"][0]["revision"] == 5
    assert sum(row["order_count"] for row in output["daily"]) == 0
    assert asyncio.run(AnalyticsProjectionService(AsyncSessionLocal).reconcile(*scope))[
        "matches"
    ]


def test_scoped_decimal_totals_creation_dates_and_cli_discrepancies():
    first, second = create_scope(), create_scope()
    for scope, order_id, total in [
        (first, 1, "99999999.99"),
        (first, 2, "0.02"),
        (second, 3, "3.45"),
    ]:
        live_order(scope, order_id, total=total)
        asyncio.run(execute(event(scope, order_id, total=total)))
    live_order(first, 4, total="42.00", status="CANCELLED")
    output = inspect(first)
    assert output["daily"] == [
        {"creation_date": "2026-10-01", "order_count": 2, "sales": "100000000.01"}
    ]
    service = AnalyticsProjectionService(AsyncSessionLocal)
    assert asyncio.run(service.reconcile(*first))["matches"]
    assert inspect(second)["daily"][0]["sales"] == "3.45"
    with pytest.raises(ValueError):
        inspect((second[0], first[1]))
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE analytics_daily_sales SET sales=sales+1 WHERE restaurant_id=:id"
            ),
            {"id": first[1]},
        )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.modules.events.cli",
            "analytics-reconcile",
            "--organization-id",
            str(first[0]),
            "--restaurant-id",
            str(first[1]),
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    difference = json.loads(result.stdout)
    assert difference["discrepancies"][0]["authoritative_sales"] == "100000000.01"
    assert not difference["matches"]
    assert asyncio.run(service.reconcile(*second))["matches"]


@pytest.mark.parametrize("same_order", [False, True])
def test_overlap_at_restaurant_lock_has_no_lost_delta(same_order):
    scope = create_scope()
    first = event(scope, 1)
    second = event(scope, 1 if same_order else 2)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def hold(_claim):
            entered.set()
            await release.wait()

        task = asyncio.create_task(
            execute(first, hooks=ExecutionHooks(before_commit=hold))
        )
        await asyncio.wait_for(entered.wait(), 5)
        other = asyncio.create_task(execute(second))
        try:
            # Observe the actual wait graph while the first effect is uncommitted.
            async def blocked():
                for _ in range(1000):
                    with engine.connect() as connection:
                        if connection.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND cardinality(pg_blocking_pids(pid))>0 AND query LIKE '%restaurants%')"
                            )
                        ):
                            return
                    await asyncio.sleep(0.01)
                raise AssertionError(
                    "Competing effect never blocked at restaurant lock"
                )

            await asyncio.wait_for(blocked(), 10)
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        select(func.count()).select_from(OrderContribution)
                    )
                    == 0
                )
        finally:
            release.set()
        assert (await task).acknowledge and (await other).acknowledge

    asyncio.run(scenario())
    assert inspect(scope)["daily"][0]["order_count"] == (1 if same_order else 2)
    assert inspect(scope)["daily"][0]["sales"] == ("12.34" if same_order else "24.68")


def test_effect_receipt_failure_rolls_back_all_projection_state():
    scope = create_scope()
    live_order(scope)
    value = event(scope, 1)

    async def fail(_claim):
        raise RuntimeError("Injected after effect and receipt flush")

    assert (
        asyncio.run(
            execute(value, hooks=ExecutionHooks(before_commit=fail), max_attempts=1)
        ).outcome
        == "consumer_failed"
    )
    assert inspect(scope)["daily"] == inspect(scope)["orders"] == []
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(EventReceipt)) == 0
        delivery_id = connection.scalar(
            select(EventDelivery.id).where(
                EventDelivery.event_id == value.event_id,
                EventDelivery.consumer_name == "analytics",
            )
        )
    asyncio.run(
        EventOperatorService(AsyncSessionLocal).replay(
            delivery_id, reason="Repair injected projection failure"
        )
    )
    assert asyncio.run(execute(value)).acknowledge
    assert asyncio.run(execute(value)).outcome == "durable_receipt_acknowledged"
    assert inspect(scope)["daily"][0]["order_count"] == 1
    assert asyncio.run(AnalyticsProjectionService(AsyncSessionLocal).reconcile(*scope))[
        "matches"
    ]


def test_rebuild_seeds_all_watermarks_preserves_receipts_and_queued_deletions():
    scope = create_scope()
    live_order(scope, 1, revision=7)
    live_order(scope, 2, revision=3, status="DRAFT", total="0.00")
    completed = event(scope, 1, revision=4)
    removed_completion = event(scope, 3, revision=4)
    deletion = event(scope, 3, revision=5, deleted=True)
    asyncio.run(execute(completed))
    service = AnalyticsProjectionService(AsyncSessionLocal)
    for _ in range(2):
        asyncio.run(service.rebuild(*scope))
    for value in [removed_completion, deletion, event(scope, 1, revision=6)]:
        assert asyncio.run(execute(value)).acknowledge
    assert inspect(scope)["daily"][0]["order_count"] == 1
    assert {
        row["order_id"]: (row["revision"], row["state"])
        for row in inspect(scope)["orders"]
    } == {1: (7, "completed"), 2: (3, "inactive"), 3: (5, "deleted")}
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(EventReceipt)) == 4
    assert asyncio.run(service.reconcile(*scope))["matches"]


def test_rebuild_failure_rolls_back_and_does_not_discard_missing_order():
    scope = create_scope()
    asyncio.run(execute(event(scope, 1)))
    before = inspect(scope)
    with pytest.raises(ValueError):
        asyncio.run(AnalyticsProjectionService(AsyncSessionLocal).rebuild(*scope))
    assert inspect(scope) == before


def test_newer_completion_replaces_prior_day_and_total():
    scope = create_scope()
    asyncio.run(execute(event(scope, 1)))
    asyncio.run(
        execute(
            event(scope, 1, revision=5, total="0.01", created=datetime(2026, 10, 2))
        )
    )
    output = inspect(scope)
    assert output["daily"] == [
        {"creation_date": "2026-10-01", "order_count": 0, "sales": "0.00"},
        {"creation_date": "2026-10-02", "order_count": 1, "sales": "0.01"},
    ]


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_real_analytics_worker_crash_recovery(tmp_path, monkeypatch, phase):
    scope = create_scope()
    value = event(scope, 1)
    settings = worker_settings()
    monkeypatch.setenv("EVENT_WORKER_TEST_ANALYTICS", "1")
    process = start_process(tmp_path, settings, pause_at=phase)
    try:
        process_phase(process, phase)
        with engine.connect() as connection:
            assert connection.scalar(
                select(func.count()).select_from(OrderContribution)
            ) == (0 if phase == "before_commit" else 1)
    finally:
        kill_process(process)
    # Restart the actual production entrypoint with its default analytics registry.
    restarted = start_process(tmp_path, settings, module=True)
    try:
        wait_for(
            lambda: (
                next(
                    row
                    for row in delivery_rows(value.event_id)
                    if row["consumer_name"] == "analytics"
                )["status"]
                == "succeeded"
            )
        )
        output = inspect(scope)
        assert output["daily"][0]["sales"] == "12.34"
        assert output["daily"][0]["order_count"] == 1
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(EventReceipt)
                    .where(EventReceipt.consumer_name == "analytics")
                )
                == 1
            )
    finally:
        kill_process(restarted)
