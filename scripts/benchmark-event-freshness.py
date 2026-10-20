"""Measure visible consumer commits using only owned disposable services."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import signal
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
VERSION = "1.0.0"


def distribution(values):
    """Nearest-rank percentiles; never manufacture values for missing effects."""
    ordered = sorted(values)
    return {
        "count": len(ordered),
        **{
            name: ordered[math.ceil(len(ordered) * fraction) - 1] if ordered else None
            for name, fraction in (("p50_ms", 0.5), ("p95_ms", 0.95), ("p99_ms", 0.99))
        },
        "max_ms": max(ordered) if ordered else None,
        "over_5000_ms": sum(value > 5000 for value in ordered),
    }


def latency_bounds(before_commit, after_commit, previous_scan, seen_at):
    """Bound real commit-to-commit latency without relying on database clocks."""
    return {
        "upper_ms": (seen_at - before_commit) * 1000,
        "lower_ms": max(0, previous_scan - after_commit) * 1000,
        "commit_bracket_ms": (after_commit - before_commit) * 1000,
        "observation_bracket_ms": (seen_at - previous_scan) * 1000,
    }


def cli(env, *arguments):
    result = subprocess.run(
        [sys.executable, "-m", "app.modules.events.cli", *arguments],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


async def operations(scope, output):
    """Separate failure rehearsal; none of these timings enter healthy samples."""
    from app.core.config import get_settings
    from app.db.database import AsyncSessionLocal
    from app.modules.events.domain.contracts import (
        OrderCompletedEvent,
        OrderCompletedPayload,
    )
    from app.modules.events.execution import CONSUMERS, ConsumerExecutionService
    from app.modules.events.repo.models import EventDelivery
    from app.modules.events.service import append_event
    from app.modules.events.worker.redis import WorkerRedisTransport
    from app.modules.orders.repo.models import Order
    from sqlalchemy import func, select
    from sqlalchemy.exc import IntegrityError
    from test_support.processes import stop_processes

    env = dict(os.environ)
    async with AsyncSessionLocal() as session, session.begin():
        order = Order(
            order_id=(await session.scalar(select(func.max(Order.order_id))) or 0)
            + 100,
            restaurant_id=scope[1],
            status="COMPLETED",
            total=Decimal("7.00"),
            subtotal=Decimal("7.00"),
        )
        session.add(order)
        await session.flush()
        envelope = OrderCompletedEvent(
            organization_id=scope[0],
            restaurant_id=scope[1],
            aggregate_id=str(order.order_id),
            aggregate_revision=1,
            occurred_at=datetime.now(UTC),
            correlation_id="operations-" + uuid4().hex,
            payload=OrderCompletedPayload(
                order_id=order.order_id, total="7.00", created_at=order.created_at
            ),
        )
        await append_event(session, envelope)
    reference = {
        key: str(getattr(envelope, key))
        for key in ("event_id", "event_type", "schema_version", "correlation_id")
    }
    execution = ConsumerExecutionService(AsyncSessionLocal)
    await execution.execute(
        event_id=envelope.event_id,
        consumer="analytics",
        reference=reference,
        worker_id="operations-healthy",
    )

    async def broken_handler(session, event):
        # Test-only handler injection: a permanent event constraint failure.
        raise IntegrityError("disposable rehearsal", {}, Exception())

    await ConsumerExecutionService(
        AsyncSessionLocal, registry={**CONSUMERS, "notification_sink": broken_handler}
    ).execute(
        event_id=envelope.event_id,
        consumer="notification_sink",
        reference=reference,
        worker_id="operations-broken",
    )
    async with AsyncSessionLocal() as session:
        selected = await session.scalar(
            select(EventDelivery.id).where(
                EventDelivery.event_id == envelope.event_id,
                EventDelivery.consumer_name == "notification_sink",
            )
        )
    before = await asyncio.to_thread(cli, env, "inspect", str(selected))
    status_failed = await asyncio.to_thread(cli, env, "status")
    replay = await asyncio.to_thread(
        cli,
        env,
        "replay",
        str(selected),
        "--reason",
        "Replaced disposable failing handler with production sink",
    )
    process = None
    with output.with_suffix(".operations.log").open("w", encoding="utf-8") as log:
        try:
            # Actual production process is killed with retained pending work.
            process = await asyncio.to_thread(
                subprocess.Popen,
                [sys.executable, "-m", "app.worker"],
                cwd=BACKEND,
                env=env,
                stdout=log,
                stderr=log,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            process.kill()
            await asyncio.to_thread(process.wait, 10)
            forced_code = process.returncode
            transport = WorkerRedisTransport(get_settings())
            await transport.open()
            try:
                stream_size_before = await transport.execute(
                    "XLEN", transport.stream_key()
                )
                # Only this runner's random namespace in its owned Redis service.
                await transport.execute("DEL", transport.stream_key())
                stream_size_after = await transport.execute(
                    "XLEN", transport.stream_key()
                )
            finally:
                await transport.close()
            process = await asyncio.to_thread(
                subprocess.Popen,
                [sys.executable, "-m", "app.worker"],
                cwd=BACKEND,
                env=env,
                stdout=log,
                stderr=log,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            deadline = time.perf_counter() + 90
            while time.perf_counter() < deadline:
                async with AsyncSessionLocal() as session:
                    statuses = list(
                        await session.scalars(
                            select(EventDelivery.status).where(
                                EventDelivery.event_id == envelope.event_id
                            )
                        )
                    )
                if statuses == ["succeeded", "succeeded"]:
                    break
                if process.poll() is not None:
                    raise RuntimeError("Recovery worker exited")
                await asyncio.sleep(0.05)
            else:
                raise RuntimeError("Operator recovery timed out")
            process.send_signal(
                signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM
            )
            await asyncio.to_thread(process.wait, 15)
            graceful_code = process.returncode
        finally:
            stop_processes(process)
    after = await asyncio.to_thread(cli, env, "inspect", str(selected))
    async with AsyncSessionLocal() as session:
        analytics_id = await session.scalar(
            select(EventDelivery.id).where(
                EventDelivery.event_id == envelope.event_id,
                EventDelivery.consumer_name == "analytics",
            )
        )
    analytics = await asyncio.to_thread(cli, env, "inspect", str(analytics_id))
    assert (
        before["status"] == "failed"
        and before["last_error_category"] == "event_constraint"
    )
    assert after["status"] == "succeeded" and after["event_id"] == before["event_id"]
    assert (
        after["correlation_id"] == before["correlation_id"]
        and len(after["attempts"]) == 2
    )
    assert (
        after["replays"][0]["replay_id"] == replay["replay_id"]
        and analytics["attempt_count"] == 1
    )
    assert graceful_code == 0 and forced_code != 0 and stream_size_after == 0
    return {
        "injection": "test-only constraint-failing sink replaced by production handler; default retry policy unchanged",
        "failed_status": status_failed,
        "before": before,
        "replay": replay,
        "after": after,
        "successful_analytics_unchanged": analytics,
        "forced_exit_code": forced_code,
        "graceful_exit_code": graceful_code,
        "stream_size_before_loss": stream_size_before,
        "stream_size_after_loss": stream_size_after,
        "recovered_status": await asyncio.to_thread(cli, env, "status"),
    }


async def measure(args):
    # Imports occur only in the child after the guarded database environment is set.
    import app.db.models  # noqa: F401 - register related ORM mappings
    from app.core.config import get_settings
    from app.core.request_id import reset_request_id, set_request_id
    from app.db.database import AsyncSessionLocal, engine
    from app.modules.auth.domain.principal import AuthenticatedPrincipal
    from app.modules.auth.repo.models import User
    from app.modules.events.domain.contracts import deserialize_event
    from app.modules.events.service import append_event
    from app.modules.inventory.domain.commands import CreateIngredient
    from app.modules.inventory.service import InventoryService
    from app.modules.orders.repo.models import Order
    from app.modules.restaurants.repo.models import Restaurant
    from app.modules.tenancy.domain.roles import MembershipRole
    from app.modules.tenancy.repo.models import Membership, Organization
    from sqlalchemy import event, text

    async with AsyncSessionLocal() as session, session.begin():
        org = Organization(name="Freshness benchmark", slug="freshness-" + uuid4().hex)
        user = User(email="benchmark@example.test", password_hash="disabled-fixture")
        session.add_all([org, user])
        await session.flush()
        session.add(
            Membership(
                user_id=user.id, organization_id=org.id, role=MembershipRole.OWNER
            )
        )
        restaurant = Restaurant(name="Measured branch", organization_id=org.id)
        session.add(restaurant)
        await session.flush()
        scope = (str(org.id), restaurant.id)
        principal = AuthenticatedPrincipal(user.id, user.email, "active", uuid4())

    starts, acknowledgements, observed = {}, {}, {}
    backlog = []
    producing = True
    epoch = time.perf_counter()

    async def observer():
        previous_scan = epoch
        while producing or len(observed) < args.bundles * 11:
            async with AsyncSessionLocal() as session:
                scan_started = time.perf_counter()
                rows = (
                    (
                        await session.execute(
                            text(
                                "SELECT r.event_id,r.consumer_name,r.outcome,e.correlation_id,e.event_type "
                                "FROM event_receipts r JOIN outbox_events e USING(event_id)"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                seen_at = time.perf_counter()
                for row in rows:
                    key = (str(row["event_id"]), row["consumer_name"])
                    observed.setdefault(
                        key,
                        {
                            **dict(row),
                            "seen_at": seen_at,
                            "previous_scan": previous_scan,
                        },
                    )
                previous_scan = scan_started
                state = (
                    await session.execute(
                        text(
                            "SELECT count(*) FILTER (WHERE status IN ('pending','processing')), "
                            "coalesce(extract(epoch FROM clock_timestamp()-min(created_at) "
                            "FILTER (WHERE status IN ('pending','processing'))),0), "
                            "count(*) FILTER (WHERE status='failed') FROM event_deliveries"
                        )
                    )
                ).one()
                backlog.append(
                    {
                        "elapsed_seconds": seen_at - epoch,
                        "depth": state[0],
                        "oldest_age_seconds": float(state[1]),
                        "failed": state[2],
                    }
                )
            if time.perf_counter() - epoch > args.bundles / args.rate + args.timeout:
                break
            await asyncio.sleep(args.poll_ms / 1000)

    def instrument(session, correlation):
        # These hooks bracket COMMIT after the producers have flushed. Receipt
        # timestamps use transaction time and cannot measure durable completion.
        event.listen(
            session.sync_session,
            "before_commit",
            lambda _: starts.__setitem__(correlation, time.perf_counter()),
        )
        event.listen(
            session.sync_session,
            "after_commit",
            lambda _: acknowledgements.__setitem__(correlation, time.perf_counter()),
        )

    semaphore = asyncio.Semaphore(args.concurrency)

    async def produce(index):
        await asyncio.sleep(max(0, epoch + index / args.rate - time.perf_counter()))
        async with semaphore:
            correlation = "freshness-" + uuid4().hex
            order_id = index * 10 + 1
            created_at = datetime(2026, 10, 19, 12)  # noqa: DTZ001 - legacy naive UTC order column
            async with AsyncSessionLocal() as session:
                instrument(session, correlation)
                async with session.begin():
                    # Synthetic committed fact fixtures isolate delivery cost;
                    # this is not a benchmark of HTTP/order state transitions.
                    session.add(
                        Order(
                            order_id=order_id,
                            restaurant_id=scope[1],
                            status="COMPLETED",
                            total=Decimal("12.50"),
                            subtotal=Decimal("12.50"),
                            revision=1,
                            created_at=created_at,
                        )
                    )
                    specs = [
                        ("order.submitted.v1", {"order_id": order_id + 1}),
                        ("order.accepted.v1", {"order_id": order_id + 2}),
                        (
                            "order.completed.v1",
                            {
                                "order_id": order_id,
                                "total": "12.50",
                                "created_at": created_at,
                            },
                        ),
                        ("order.cancelled.v1", {"order_id": order_id + 3}),
                        (
                            "order.deleted.v1",
                            {
                                "order_id": order_id + 4,
                                "prior_status": "COMPLETED",
                                "total": "12.50",
                                "created_at": created_at,
                            },
                        ),
                        (
                            "menu.updated.v1",
                            {
                                "operation": "edited",
                                "target_type": "menu",
                                "target_id": index + 1,
                                "menu_id": index + 1,
                            },
                        ),
                    ]
                    for kind, payload in specs:
                        await append_event(
                            session,
                            deserialize_event(
                                {
                                    "event_id": uuid4(),
                                    "event_type": kind,
                                    "schema_version": 1,
                                    "organization_id": scope[0],
                                    "restaurant_id": scope[1],
                                    "aggregate_type": "menu"
                                    if kind.startswith("menu")
                                    else "order",
                                    "aggregate_id": str(
                                        payload.get("order_id", index + 1)
                                    ),
                                    "aggregate_revision": 1,
                                    "occurred_at": datetime.now(UTC),
                                    "correlation_id": correlation,
                                    "payload": payload,
                                }
                            ),
                        )
                    await session.flush()
            correlation += "-inventory"
            token = set_request_id(correlation)
            try:
                async with AsyncSessionLocal() as session:
                    instrument(session, correlation)
                    await InventoryService(session, principal).create(
                        scope[1],
                        CreateIngredient(
                            name=f"Low ingredient {index}",
                            unit="g",
                            reorder_threshold=Decimal(5),
                            opening_quantity=Decimal(1),
                            idempotency_key=uuid4().hex,
                        ),
                    )
            finally:
                reset_request_id(token)

    worker = None
    log_path = args.output.with_suffix(".worker.log")
    env = dict(os.environ)
    try:
        with log_path.open("w", encoding="utf-8") as log:
            worker = subprocess.Popen(  # noqa: ASYNC220 - startup precedes measurement
                [sys.executable, "-m", "app.worker"],
                cwd=BACKEND,
                env=env,
                stdout=log,
                stderr=log,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            # Warm infrastructure/groups, excluding startup from the healthy sample.
            from app.modules.events.worker.redis import WorkerRedisTransport

            transport = WorkerRedisTransport(get_settings())
            await transport.open()
            try:
                redis_info = await transport.execute("INFO", "server")
                for _ in range(200):
                    if worker.poll() is not None:
                        raise RuntimeError("Worker exited during startup")
                    exists = await transport.execute("EXISTS", transport.stream_key())
                    groups = (
                        await transport.execute(
                            "XINFO", "GROUPS", transport.stream_key()
                        )
                        if exists
                        else []
                    )
                    if len(groups) == 3:
                        break
                    await asyncio.sleep(0.05)
                else:
                    raise RuntimeError("Worker groups did not become ready")
            finally:
                await transport.close()
            epoch = time.perf_counter()
            task = asyncio.create_task(observer())
            try:
                await asyncio.gather(*(produce(index) for index in range(args.bundles)))
            except BaseException:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise
            finally:
                producing = False
            await task
            healthy_exit = worker.poll() is None
            if healthy_exit:
                worker.send_signal(
                    signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM
                )
                await asyncio.to_thread(worker.wait, 15)
            graceful = healthy_exit and worker.returncode == 0
        async with AsyncSessionLocal() as session:
            deliveries = (
                (
                    await session.execute(
                        text(
                            "SELECT d.event_id,d.consumer_name,d.status,e.correlation_id,e.event_type "
                            "FROM event_deliveries d JOIN outbox_events e USING(event_id)"
                        )
                    )
                )
                .mappings()
                .all()
            )
            retained = {}
            for table in (
                "outbox_events",
                "event_deliveries",
                "event_receipts",
                "event_delivery_attempts",
                "event_delivery_replays",
                "analytics_order_contributions",
                "analytics_daily_sales",
                "alert_episodes",
                "alert_ingredient_states",
                "notification_stubs",
                "event_diagnostics",
            ):
                retained[table] = await session.scalar(
                    text(f"SELECT count(*) FROM {table}")
                )
            effects = {
                "sales": str(
                    await session.scalar(
                        text("SELECT sum(sales) FROM analytics_daily_sales")
                    )
                ),
                "order_count": await session.scalar(
                    text("SELECT sum(order_count) FROM analytics_daily_sales")
                ),
                "created_stubs": await session.scalar(
                    text(
                        "SELECT count(*) FROM notification_stubs WHERE outcome='created'"
                    )
                ),
            }
            mix = dict(
                Counter(
                    row[0]
                    for row in (
                        await session.execute(
                            text("SELECT event_type FROM outbox_events")
                        )
                    ).all()
                )
            )
            revision = await session.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            postgres = await session.scalar(text("SELECT version()"))
        samples = []
        for delivery in deliveries:
            key = (str(delivery["event_id"]), delivery["consumer_name"])
            receipt = observed.get(key)
            correlation = delivery["correlation_id"]
            samples.append(
                {
                    **dict(delivery),
                    "event_id": str(delivery["event_id"]),
                    "outcome": receipt["outcome"] if receipt else None,
                    **(
                        latency_bounds(
                            starts[correlation],
                            acknowledgements[correlation],
                            receipt["previous_scan"],
                            receipt["seen_at"],
                        )
                        if receipt
                        else {"upper_ms": None, "lower_ms": None}
                    ),
                }
            )
        summaries = {}
        for consumer in ("analytics", "alerts", "notification_sink"):
            selected = [s for s in samples if s["consumer_name"] == consumer]
            summaries[consumer] = {
                **distribution(
                    [s["upper_ms"] for s in selected if s["upper_ms"] is not None]
                ),
                "expected": len(selected),
                "lower_bounds": distribution(
                    [s["lower_ms"] for s in selected if s["lower_ms"] is not None]
                ),
                "certain_over_5000_ms": sum(
                    s["lower_ms"] is not None and s["lower_ms"] > 5000 for s in selected
                ),
                "missing": sum(s["outcome"] is None for s in selected),
                "outcomes": dict(Counter(s["outcome"] for s in selected)),
            }
        status = await asyncio.to_thread(cli, env, "status")
        inspection = await asyncio.to_thread(
            cli, env, "inspect", str(await delivery_id(engine))
        )
        scope_args = ["--organization-id", scope[0], "--restaurant-id", str(scope[1])]
        reconciliation = await asyncio.to_thread(
            cli, env, "analytics-reconcile", *scope_args
        )
        initialization = await asyncio.to_thread(
            cli,
            env,
            "initialize",
            *scope_args,
            "--maintenance-confirmed",
            "--reason",
            "Disposable freshness rehearsal",
        )
        rerun = await asyncio.to_thread(
            cli,
            env,
            "initialize",
            *scope_args,
            "--maintenance-confirmed",
            "--reason",
            "Disposable repeat",
        )
        rebuild = await asyncio.to_thread(
            cli,
            env,
            "analytics-rebuild",
            *scope_args,
            "--maintenance-confirmed",
            "--reason",
            "Disposable rebuild rehearsal",
        )
        after = await asyncio.to_thread(cli, env, "analytics-reconcile", *scope_args)
        result = {
            "script_version": VERSION,
            "measured_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "postgres": postgres,
            "redis_version": redis_info.get("redis_version")
            if isinstance(redis_info, dict)
            else str(redis_info),
            "repository_head": subprocess.check_output(  # noqa: ASYNC221 - measurement has finished
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "migration_head": revision,
            "bundles": args.bundles,
            "rate_bundles_per_second": args.rate,
            "producer_concurrency": args.concurrency,
            "poll_ms": args.poll_ms,
            "event_mix": mix,
            "worker_settings": {
                key: value
                for key, value in get_settings().model_dump(mode="json").items()
                if key.startswith("event_worker_")
            },
            "consumers": summaries,
            "samples": samples,
            "backlog_samples": backlog,
            "status_after_drain": status,
            "retained_before_maintenance": retained,
            "effects": effects,
            "graceful_shutdown": graceful,
            "inspection": inspection,
            "maintenance": {
                "reconcile_before": reconciliation,
                "initialize": initialization,
                "rerun": rerun,
                "rebuild": rebuild,
                "reconcile_after": after,
            },
        }
        result["correct"] = (
            len(samples) == args.bundles * 11
            and all(
                s["status"] == "succeeded" and s["outcome"] == "processed"
                for s in samples
            )
            and effects
            == {
                "sales": str(Decimal("12.50") * args.bundles),
                "order_count": args.bundles,
                "created_stubs": args.bundles,
            }
            and retained["event_diagnostics"] == args.bundles * 6
            and retained["alert_episodes"] == args.bundles
            and graceful
            and reconciliation["matches"]
            and after["matches"]
            and initialization["operation_id"] == rerun["operation_id"]
        )
        if args.operations:
            result["operations"] = await operations(scope, args.output)
        args.output.write_text(
            json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
        )
        if not result["correct"]:
            raise RuntimeError(
                "Benchmark correctness/reconciliation failed; inspect retained report"
            )
    finally:
        from test_support.processes import stop_processes

        if worker:
            stop_processes(worker)
        await engine.dispose()


async def delivery_id(engine):
    from sqlalchemy import text

    async with engine.connect() as connection:
        return await connection.scalar(
            text("SELECT id FROM event_deliveries ORDER BY id LIMIT 1")
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundles", type=int, default=40)
    parser.add_argument("--rate", type=float, default=0.5)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--poll-ms", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--operations",
        action="store_true",
        help="Also rehearse isolated CLI failure/repair/replay and stream loss",
    )
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not (
        1 <= args.bundles <= 10000
        and 1 <= args.concurrency <= 32
        and 0 < args.rate <= 1000
        and 5 <= args.poll_ms <= 1000
        and 0 < args.timeout <= 600
    ):
        parser.error("Workload arguments outside bounded ranges")
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.child:
        from test_support.disposable_postgres import read_test_url

        read_test_url()
        if os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL"):
            raise ValueError("Child requires the allocated test database")
        asyncio.run(measure(args))
        return
    from test_support.disposable_postgres import disposable_database
    from validate import services

    with (
        services(False) as base,
        disposable_database(
            prefix="restaurantos_freshness", test_url=base["TEST_DATABASE_URL"]
        ) as database,
    ):
        env = database.environment(base)
        env["PYTHONPATH"] = str(BACKEND) + os.pathsep + str(ROOT / "scripts")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=env,
            check=True,
        )
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--child"],
            cwd=ROOT,
            env=env,
            check=True,
        )


if __name__ == "__main__":
    main()
