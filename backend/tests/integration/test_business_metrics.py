"""Committed activity and bounded operator metrics against real PostgreSQL."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, time, timedelta
from decimal import Decimal
from threading import Event
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import business_collection
from app.core.business_collection import BusinessCollector, read_snapshot
from app.core.business_metrics import BusinessMetrics
from app.core.config import get_settings
from app.db.database import AsyncSessionLocal
import app.main as main
from app.main import app
from app.modules.inventory.service import record_baseline_inventory_episode
from app.modules.orders import service as order_service
from conftest import engine
from integration.test_inventory_episodes import change_stock, create_ingredient
from integration.test_order_inventory import (
    create_menu_item,
    create_order,
    create_restaurant,
    set_recipe,
    update_order,
)
from test_alert_projection import deliver, event_rows
from test_analytics_projection import event, execute, live_order
from app.modules.events.execution import EventTransientFailure, ExecutionHooks
from test_event_worker import create_scope, wait_for
from test_http_observability import collector, instrumented_client

CANARY = "private_issue_63_canary"
PREFIX = "restaurantos.business."


def wire_points(received, name):
    return [
        point
        for batch in received
        for resource in batch.get("resourceMetrics", [])
        for scope in resource["scopeMetrics"]
        for metric in scope["metrics"]
        if metric["name"] == PREFIX + name
        for point in (metric.get("sum") or metric["gauge"])["dataPoints"]
    ]


def counter_value(received, name, label, value):
    return max(
        (
            int(point["asInt"])
            for point in wire_points(received, name)
            if point.get("attributes")
            == [{"key": label, "value": {"stringValue": value}}]
        ),
        default=0,
    )


def test_only_committed_order_transitions_are_exported(monkeypatch, auth_user):
    with collector("outage") as (endpoint, received, entered, reject):
        with instrumented_client(monkeypatch, auth_user, endpoint) as (client, _):
            branch = create_restaurant(client)
            item = create_menu_item(client, branch)
            order = create_order(client, branch, item, key=CANARY, notes=CANARY)
            order_id = order.json()["order_id"]
            replay = create_order(client, branch, item, key=CANARY, notes=CANARY)
            assert replay.json() == order.json()
            assert update_order(client, order_id, "DRAFT").status_code == 200
            # Status is assigned in the service before payment validation fails.
            rolled_back = client.put(
                f"/api/orders/{order_id}",
                json={"status": "SUBMITTED", "payment_status": "invalid"},
            )
            assert rolled_back.status_code == 422
            append = order_service.CommandEvents.append

            async def fail_after_append(self, *args, **kwargs):
                await append(self, *args, **kwargs)
                raise RuntimeError(CANARY)

            with monkeypatch.context() as rollback:
                rollback.setattr(
                    order_service.CommandEvents, "append", fail_after_append
                )
                assert update_order(client, order_id, "SUBMITTED").status_code == 500
            assert client.get(f"/api/orders/{order_id}").json()["status"] == "DRAFT"
            with engine.begin() as db:
                db.execute(
                    text("""
                    CREATE FUNCTION issue63_fail_commit() RETURNS trigger
                    LANGUAGE plpgsql AS $$
                    BEGIN
                        RAISE EXCEPTION 'deferred commit failure';
                    END
                    $$
                """)
                )
                db.execute(
                    text("""
                    CREATE CONSTRAINT TRIGGER issue63_fail_commit
                    AFTER UPDATE ON orders DEFERRABLE INITIALLY DEFERRED
                    FOR EACH ROW WHEN (NEW.status = 'SUBMITTED')
                    EXECUTE FUNCTION issue63_fail_commit()
                """)
                )
            try:
                assert update_order(client, order_id, "SUBMITTED").status_code == 500
                assert client.get(f"/api/orders/{order_id}").json()["status"] == "DRAFT"
                assert not any(
                    row.event_type == "order.submitted.v1" for _, row in event_rows()
                )
            finally:
                with engine.begin() as db:
                    db.execute(text("DROP TRIGGER issue63_fail_commit ON orders"))
                    db.execute(text("DROP FUNCTION issue63_fail_commit()"))
            for state in (
                "SUBMITTED",
                "SUBMITTED",
                "ACCEPTED",
                "PREPARING",
                "READY",
                "COMPLETED",
                "COMPLETED",
            ):
                assert update_order(client, order_id, state).status_code == 200

            # While the exporter receives 503s, a separate order still commits.
            entered.clear()
            reject.set()
            assert entered.wait(5)
            another = create_order(client, branch, item).json()["order_id"]
            for _ in range(2):
                assert update_order(client, another, "CANCELLED").status_code == 200
            assert client.get(f"/api/orders/{another}").json()["status"] == "CANCELLED"
            reject.clear()
            wait_for(
                lambda: (
                    counter_value(
                        received, "orders.transitions", "transition", "CANCELLED"
                    )
                    == 1
                )
            )
            points = wire_points(received, "orders.transitions")
            assert CANARY not in json.dumps(points)
            assert not wire_points(received, "collection.success")
            assert {
                (
                    point["attributes"][0]["key"],
                    point["attributes"][0]["value"]["stringValue"],
                    int(point["asInt"]),
                )
                for point in points
            } == {
                ("transition", state, 1)
                for state in ("SUBMITTED", "COMPLETED", "CANCELLED")
            }


def snapshot(*, include_thb=True):
    return asyncio.run(read_snapshot(AsyncSessionLocal, include_thb=include_thb))


def test_rejected_attempts_are_separate_from_openings_and_current_state(
    monkeypatch, auth_user
):
    with collector("success") as (endpoint, received, _, _):
        with instrumented_client(monkeypatch, auth_user, endpoint) as (client, _):
            branch = create_restaurant(client)
            ingredient = create_ingredient(client, branch, name=CANARY)
            ingredient_id = ingredient["id"]
            item = create_menu_item(client, branch)
            assert (
                set_recipe(
                    client, item, [{"ingredient_id": ingredient_id, "quantity": "11"}]
                ).status_code
                == 200
            )
            for _ in range(2):
                assert create_order(client, branch, item, key=CANARY).status_code == 409
                assert (
                    change_stock(
                        client, branch, ingredient_id, CANARY, "waste", "11"
                    ).status_code
                    == 409
                )
            empty = snapshot()
            assert (
                empty.operational_openings,
                empty.active_ingredients,
                empty.active_alerts,
            ) == (0, 0, 0)
            for _ in range(2):
                assert (
                    change_stock(
                        client, branch, ingredient_id, "open", "waste", "5"
                    ).status_code
                    == 201
                )
            opened = snapshot()
            assert (
                opened.operational_openings,
                opened.active_ingredients,
                opened.active_alerts,
            ) == (1, 1, 0)
            low = next(
                row for _, row in event_rows() if row.event_type == "inventory.low.v1"
            )
            assert asyncio.run(deliver(low, "alerts")).acknowledge
            assert (
                asyncio.run(deliver(low, "alerts")).outcome
                == "durable_receipt_acknowledged"
            )
            assert snapshot().active_alerts == 1
            assert (
                change_stock(
                    client, branch, ingredient_id, "recover", "receipt", "1"
                ).status_code
                == 201
            )
            resolved = snapshot()
            assert (
                resolved.operational_openings,
                resolved.active_ingredients,
                resolved.active_alerts,
            ) == (1, 0, 0)

            baseline = create_ingredient(client, branch, name="Legacy ingredient")
            with engine.begin() as db:
                db.execute(
                    text(
                        "UPDATE inventory_balances SET quantity=5 WHERE ingredient_id=:id"
                    ),
                    {"id": baseline["id"]},
                )
            assert snapshot().active_ingredients == 1
            assert snapshot().baseline_openings == 0

            async def initialize():
                async with AsyncSessionLocal() as session, session.begin():
                    return await record_baseline_inventory_episode(
                        session,
                        UUID(auth_user["organization_id"]),
                        branch,
                        baseline["id"],
                    )

            assert (
                asyncio.run(initialize()).episode_id
                == asyncio.run(initialize()).episode_id
            )
            initialized = snapshot()
            assert (
                initialized.operational_openings,
                initialized.baseline_openings,
                initialized.active_ingredients,
            ) == (1, 1, 1)
            for category in (
                "order_stock_insufficient",
                "inventory_stock_insufficient",
            ):
                wait_for(
                    lambda: (
                        counter_value(
                            received, "stock.rejections", "category", category
                        )
                        == 2
                    )
                )
            assert CANARY not in json.dumps(wire_points(received, "stock.rejections"))


@pytest.fixture
def aggregate_metrics():
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], shutdown_on_exit=False)
    settings = get_settings().model_copy(update={"monitoring_business_sales_thb": True})
    metrics = BusinessCollector(BusinessMetrics(provider).meter, settings)

    def points():
        return {
            (
                metric.name.removeprefix(PREFIX),
                tuple(point.attributes.items()),
            ): point.value
            for resource in reader.get_metrics_data().resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
            for point in metric.data.data_points
        }

    try:
        yield metrics, points
    finally:
        provider.shutdown()


def test_retained_sales_and_export_match_projection_through_replay_and_deletion(
    authenticated_client, auth_user, aggregate_metrics
):
    metrics, points = aggregate_metrics
    branch = create_restaurant(authenticated_client)
    scope = (UUID(auth_user["organization_id"]), branch)
    second = create_scope()
    day = snapshot().as_of.date()
    today = datetime.combine(day, time())
    start = today - timedelta(days=6)
    end = today + timedelta(days=1)
    for group, order, created, amount in (
        (scope, 100, start - timedelta(microseconds=1), "7.00"),
        (scope, 101, start, "99999999.99"),
        (second, 102, end - timedelta(microseconds=1), "0.02"),
        (second, 103, end, "9.00"),
    ):
        live_order(group, order, created=created, total=amount)
        message = event(group, order, created=created, total=amount)
        assert asyncio.run(execute(message)).acknowledge
        assert asyncio.run(execute(message)).outcome == "durable_receipt_acknowledged"
        assert asyncio.run(
            execute(event(group, order, created=created, total=amount))
        ).acknowledge
    assert asyncio.run(
        execute(event(scope, 105, 5, deleted=True, created=today))
    ).acknowledge
    assert asyncio.run(execute(event(scope, 105, 4, created=today))).acknowledge
    assert snapshot(include_thb=False).sales_thb is None

    def reconcile(expected_count, expected_amount):
        sampled = snapshot()
        assert (sampled.completed_orders, sampled.sales_thb) == (
            expected_count,
            expected_amount,
        )
        with engine.connect() as db:
            assert db.execute(
                text(
                    "SELECT sum(order_count), sum(sales) FROM analytics_daily_sales "
                    "WHERE creation_date >= :start AND creation_date < :end"
                ),
                {"start": start.date(), "end": end.date()},
            ).one() == (expected_count, expected_amount)
        asyncio.run(metrics.collect(AsyncSessionLocal))
        exported = points()
        assert exported["sales.retained_orders_7d", ()] == expected_count
        assert exported["sales.retained_amount_7d", ()] == float(expected_amount)
        assert exported["collection.success", ()] == 1
        assert exported["collection.last_success", ()] >= sampled.as_of.timestamp()
        assert not any(
            value
            for (name, _), value in exported.items()
            if name == "analytics.deliveries"
        )

    reconcile(2, Decimal("100000000.01"))
    assert authenticated_client.delete("/api/orders/101").status_code == 204
    assert snapshot().analytics_backlog["queued"][0] == 1
    assert snapshot().completed_orders == 2
    deleted = next(
        row
        for _, row in event_rows()
        if row.event_type == "order.deleted.v1" and row.aggregate_id == "101"
    )
    assert asyncio.run(execute(deleted)).acknowledge
    reconcile(1, Decimal("0.02"))
    foreign_url = f"/api/restaurants/{second[1]}/analytics/dashboard"
    assert authenticated_client.get(foreign_url).status_code == 404
    with TestClient(app) as anonymous:
        assert anonymous.get(foreign_url).status_code == 401
        assert anonymous.get("/metrics").status_code == 404


def test_collection_failure_and_postgresql_statement_timeout_recover(
    aggregate_metrics, monkeypatch, caplog
):
    metrics, points = aggregate_metrics
    assert points() == {("collection.success", ()): 0}
    asyncio.run(metrics.collect(AsyncSessionLocal))
    valid = points()
    assert valid["sales.retained_orders_7d", ()] == 0
    assert valid["collection.success", ()] == 1
    last = valid["collection.last_success", ()]
    query = business_collection.operator_completed_sales

    async def failed(session, *_args, **_kwargs):
        await session.execute(text(f"SELECT {CANARY}"))

    async def slow(session, *_args, **_kwargs):
        await session.execute(text("SELECT pg_sleep(10)"))

    async def attempt_write(session, *_args, **_kwargs):
        await session.execute(text("DELETE FROM analytics_daily_sales WHERE false"))

    for broken in (failed, slow):
        monkeypatch.setattr(business_collection, "operator_completed_sales", broken)
        asyncio.run(metrics.collect(AsyncSessionLocal))
        failed_points = points()
        assert failed_points["collection.success", ()] == 0
        assert failed_points["collection.last_success", ()] == last
        assert CANARY not in caplog.text
    with pytest.raises(DBAPIError) as timeout:
        snapshot()
    assert timeout.value.orig.sqlstate == "57014"
    monkeypatch.setattr(business_collection, "operator_completed_sales", attempt_write)
    with pytest.raises(DBAPIError) as read_only:
        snapshot()
    assert read_only.value.orig.sqlstate == "25006"
    monkeypatch.setattr(business_collection, "operator_completed_sales", query)
    asyncio.run(metrics.collect(AsyncSessionLocal))
    assert points()["collection.last_success", ()] > last
    assert points()["collection.success", ()] == 1


def test_collection_observes_pending_retry_and_terminal_without_a_worker(
    aggregate_metrics,
):
    metrics, points = aggregate_metrics
    scope = create_scope()
    created = datetime.combine(snapshot().as_of.date(), time())
    queued, retry, terminal, inflight, recovery = (
        event(scope, order, created=created) for order in range(1, 6)
    )

    async def fail(_):
        raise EventTransientFailure(CANARY)

    for value, attempts, outcome in (
        (retry, 8, "consumer_retry_scheduled"),
        (terminal, 1, "consumer_failed"),
    ):
        result = asyncio.run(
            execute(
                value, hooks=ExecutionHooks(before_commit=fail), max_attempts=attempts
            )
        )
        assert result.outcome == outcome
    # Place leases either side of the database clock and keep the real retry
    # delayed throughout the assertion, independently of host timing.
    with engine.begin() as db:
        db.execute(
            text(
                "UPDATE event_deliveries SET next_attempt_at=now()+interval '1 hour' "
                "WHERE event_id=:event AND consumer_name='analytics'"
            ),
            {"event": retry.event_id},
        )
        for value, lease_seconds in ((inflight, 3600), (recovery, -3600)):
            db.execute(
                text(
                    "UPDATE event_deliveries SET status='processing', claim_owner='test', "
                    "claim_token=gen_random_uuid(), claim_expires_at=now()+:seconds*interval '1 second' "
                    "WHERE event_id=:event AND consumer_name='analytics'"
                ),
                {"event": value.event_id, "seconds": lease_seconds},
            )
    asyncio.run(metrics.collect(AsyncSessionLocal))
    previous = points()
    assert previous["collection.success", ()] == 1
    assert previous["sales.retained_orders_7d", ()] == 0
    for state in ("queued", "retry_delayed", "terminal", "in_flight", "recovery_due"):
        assert previous["analytics.deliveries", (("state", state),)] == 1
    # With the worker stopped, the same work gets older while the source stays fresh.
    asyncio.run(metrics.collect(AsyncSessionLocal))
    current = points()
    queue_age = ("analytics.oldest", (("state", "queued"),))
    assert current[queue_age] > previous[queue_age]
    assert (
        current["collection.last_success", ()] > previous["collection.last_success", ()]
    )
    assert asyncio.run(execute(queued)).acknowledge
    asyncio.run(metrics.collect(AsyncSessionLocal))
    assert points()["sales.retained_orders_7d", ()] == 1
    assert points()["analytics.deliveries", (("state", "queued"),)] == 0


def test_repeated_exports_cannot_refresh_a_stopped_sampler(monkeypatch, auth_user):
    recover = Event()
    source = business_collection.read_snapshot
    first = True

    async def stale_source(sessions, *, include_thb):
        nonlocal first
        if first:
            first = False
            sample = await source(sessions, include_thb=include_thb)
            return replace(sample, as_of=sample.as_of - timedelta(minutes=5))
        while not recover.is_set():
            await asyncio.sleep(0.01)
        return await source(sessions, include_thb=include_thb)

    monkeypatch.setattr(business_collection, "read_snapshot", stale_source)
    monkeypatch.setattr(
        main,
        "settings",
        main.settings.model_copy(
            update={
                "monitoring_business_aggregates_enabled": True,
                "monitoring_business_collection_seconds": 0.1,
            }
        ),
    )
    with collector("success") as (endpoint, received, _, _):
        with instrumented_client(monkeypatch, auth_user, endpoint):
            name = "collection.last_success"
            wait_for(lambda: len(wire_points(received, name)) >= 2)
            stale = wire_points(received, name)
            assert len({point["timeUnixNano"] for point in stale}) >= 2
            assert len({point["asDouble"] for point in stale}) == 1
            assert int(stale[-1]["timeUnixNano"]) / 1e9 - stale[-1]["asDouble"] > 60
            assert wire_points(received, "sales.retained_orders_7d")
            assert not wire_points(received, "sales.retained_amount_7d")
            recover.set()
            wait_for(
                lambda: (
                    wire_points(received, name)[-1]["asDouble"] > stale[-1]["asDouble"]
                )
            )
