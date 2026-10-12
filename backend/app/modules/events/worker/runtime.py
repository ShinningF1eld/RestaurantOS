"""Bounded relay, PostgreSQL recovery, and Redis consumer-group loops."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.events.domain.contracts import ConsumerName
from app.modules.events.domain.subscriptions import consumers_for
from app.modules.events.repo.worker_queries import (
    DeliveryClaim,
    claim_due_deliveries,
    database_time,
    defer_claim_after_transport_failure,
    load_stored_delivery,
    observe_publication,
    reset_observations_before,
    retained_work_counts,
)
from app.modules.events.worker.redis import (
    WorkerFailureKind,
    WorkerRedisFailure,
    WorkerRedisTransport,
)
from app.modules.events.worker.streams import (
    EventStreams,
    PendingMessage,
    StreamMessage,
)


logger = logging.getLogger("restaurantos.event_worker")


@dataclass(frozen=True, slots=True)
class WorkerHooks:
    """Optional process-test barriers at the two ambiguous crash boundaries."""

    after_claim: Callable[[DeliveryClaim], Awaitable[None]] | None = None
    after_publish: Callable[[DeliveryClaim, str], Awaitable[None]] | None = None


class EventWorker:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        *,
        worker_id: str | None = None,
        redis: WorkerRedisTransport | None = None,
        hooks: WorkerHooks | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.worker_id = worker_id or f"worker-{uuid4().hex}"
        if len(self.worker_id) > 80:
            raise ValueError("Worker identity must be at most 80 characters")
        self.redis = redis or WorkerRedisTransport(settings)
        self.streams = EventStreams(self.redis)
        self.hooks = hooks or WorkerHooks()
        self._stream_loss_cutoff: datetime | None = None

    async def run(self, stop: asyncio.Event) -> None:
        """Open independent infrastructure and stop loops within a fixed grace."""
        await self.redis.open()
        logger.info(
            "event_worker_started",
            extra={"event": "worker_started", "worker_id": self.worker_id},
        )
        tasks = [
            asyncio.create_task(self._relay_loop(stop), name="event-relay"),
            asyncio.create_task(self._recovery_loop(stop), name="event-recovery"),
        ]
        tasks.extend(
            asyncio.create_task(
                self._consumer_loop(group, stop), name=f"events-{group}"
            )
            for group in self._groups()
        )
        try:
            await stop.wait()
        finally:
            stop.set()
            _, pending = await asyncio.wait(
                tasks, timeout=self.settings.event_worker_shutdown_grace_seconds
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                async with asyncio.timeout(
                    self.settings.event_worker_shutdown_grace_seconds
                ):
                    await self.redis.close()
            except WorkerRedisFailure as error:
                self._log_redis_failure(
                    error,
                    outcome="shutdown_close_failed",
                    consumer_name=None,
                )
            except TimeoutError:
                self._log_redis_failure(
                    WorkerRedisFailure(WorkerFailureKind.TIMEOUT),
                    outcome="shutdown_close_failed",
                    consumer_name=None,
                )
            logger.info(
                "event_worker_stopped",
                extra={"event": "worker_stopped", "worker_id": self.worker_id},
            )

    @staticmethod
    def _groups() -> tuple[ConsumerName, ...]:
        return ("analytics", "alerts", "notification_sink")

    def _initial_backoff(self) -> int:
        return self.settings.event_worker_infra_backoff_initial_ms

    def _next_backoff(self, current: int) -> int:
        return min(
            self.settings.event_worker_infra_backoff_max_ms,
            max(self._initial_backoff(), current * 2),
        )

    async def _wait(self, stop: asyncio.Event, delay_ms: int) -> None:
        if stop.is_set():
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay_ms / 1000)
        except TimeoutError:
            pass

    def _log_redis_failure(
        self,
        error: WorkerRedisFailure,
        *,
        outcome: str,
        consumer_name: str | None,
        event_id: UUID | None = None,
        claim: DeliveryClaim | None = None,
    ) -> None:
        logger.warning(
            "event_worker_redis_failure",
            extra={
                "event": "worker_redis_failure",
                "worker_id": self.worker_id,
                "consumer_name": consumer_name,
                "event_id": str(event_id) if event_id else None,
                "claim_id": str(claim.claim_token) if claim else None,
                "correlation_id": claim.correlation_id if claim else None,
                "failure_category": error.kind.value,
                "outcome": outcome,
            },
        )

    def _log_database_failure(
        self,
        *,
        outcome: str,
        consumer_name: str | None = None,
        event_id: UUID | None = None,
        claim: DeliveryClaim | None = None,
    ) -> None:
        logger.warning(
            "event_worker_database_failure",
            extra={
                "event": "worker_database_failure",
                "worker_id": self.worker_id,
                "consumer_name": consumer_name,
                "event_id": str(event_id) if event_id else None,
                "claim_id": str(claim.claim_token) if claim else None,
                "correlation_id": claim.correlation_id if claim else None,
                "failure_category": "postgres_unavailable",
                "outcome": outcome,
            },
        )

    async def _relay_loop(self, stop: asyncio.Event) -> None:
        backoff = self._initial_backoff()
        while not stop.is_set():
            try:
                claims = await claim_due_deliveries(
                    self.sessions,
                    owner=self.worker_id,
                    limit=self.settings.event_worker_claim_batch_size,
                    lease_seconds=self.settings.event_worker_claim_lease_seconds,
                    republish_after_seconds=(
                        self.settings.event_worker_republish_stall_seconds
                    ),
                )
                if claims:
                    semaphore = asyncio.Semaphore(
                        self.settings.event_worker_relay_concurrency
                    )
                    failures = await asyncio.gather(
                        *(self._publish_claim(claim, semaphore) for claim in claims)
                    )
                    if any(failures):
                        await self._wait(stop, backoff)
                        backoff = self._next_backoff(backoff)
                        continue
                backoff = self._initial_backoff()
                await self._wait(
                    stop, self.settings.event_worker_recovery_scan_interval_ms
                )
            except asyncio.CancelledError:
                raise
            except (SQLAlchemyError, OSError, TimeoutError):
                self._log_database_failure(outcome="relay_paused")
                await self._wait(stop, backoff)
                backoff = self._next_backoff(backoff)
            except Exception:
                logger.error(
                    "event_worker_relay_loop_failed",
                    extra={
                        "event": "worker_loop_failure",
                        "worker_id": self.worker_id,
                        "failure_category": "worker_internal",
                        "outcome": "relay_paused",
                    },
                )
                await self._wait(stop, backoff)
                backoff = self._next_backoff(backoff)

    async def _publish_claim(
        self, claim: DeliveryClaim, semaphore: asyncio.Semaphore
    ) -> bool:
        async with semaphore:
            try:
                if self.hooks.after_claim is not None:
                    await self.hooks.after_claim(claim)
                message_id = await self.streams.publish(claim)
                if self.hooks.after_publish is not None:
                    await self.hooks.after_publish(claim, message_id)
                owned = await observe_publication(self.sessions, claim)
                logger.info(
                    "event_worker_publication_observed",
                    extra={
                        "event": "worker_publication",
                        "event_id": str(claim.event_id),
                        "consumer_name": claim.consumer_name,
                        "worker_id": self.worker_id,
                        "claim_id": str(claim.claim_token),
                        "correlation_id": claim.correlation_id,
                        "transport_message_id": message_id,
                        "outcome": "published" if owned else "claim_lost",
                    },
                )
                return False
            except asyncio.CancelledError:
                raise
            except WorkerRedisFailure as error:
                delay = max(
                    self._initial_backoff(),
                    self.settings.event_worker_redis_operation_budget_ms * 2,
                )
                delay = min(delay, self.settings.event_worker_infra_backoff_max_ms)
                try:
                    await defer_claim_after_transport_failure(
                        self.sessions,
                        claim,
                        retry_after_ms=delay,
                        failure_category=f"redis_{error.kind.value}",
                    )
                except SQLAlchemyError:
                    self._log_database_failure(
                        outcome="claim_cooldown_unrecorded", claim=claim
                    )
                self._log_redis_failure(
                    error,
                    outcome="publication_deferred",
                    consumer_name=claim.consumer_name,
                    event_id=claim.event_id,
                    claim=claim,
                )
                return True
            except SQLAlchemyError:
                self._log_database_failure(
                    outcome="publication_observation_unrecorded", claim=claim
                )
                return True

    async def _recovery_loop(self, stop: asyncio.Event) -> None:
        backoff = self._initial_backoff()
        while not stop.is_set():
            try:
                await self.streams.ensure_groups()
                stream_size = await self.streams.length()
                if stream_size == 0:
                    if self._stream_loss_cutoff is None:
                        self._stream_loss_cutoff = await database_time(self.sessions)
                    recovered = await reset_observations_before(
                        self.sessions,
                        cutoff=self._stream_loss_cutoff,
                        limit=self.settings.event_worker_recovery_batch_size,
                    )
                    if recovered < self.settings.event_worker_recovery_batch_size:
                        self._stream_loss_cutoff = None
                elif self._stream_loss_cutoff is not None:
                    recovered = await reset_observations_before(
                        self.sessions,
                        cutoff=self._stream_loss_cutoff,
                        limit=self.settings.event_worker_recovery_batch_size,
                    )
                    if recovered < self.settings.event_worker_recovery_batch_size:
                        self._stream_loss_cutoff = None
                else:
                    recovered = 0

                work = await retained_work_counts(self.sessions)
                pending_count = 0
                for group in self._groups():
                    pending_count += await self.streams.pending_count(group)
                logger.info(
                    "event_worker_recovery_scan",
                    extra={
                        "event": "worker_recovery_scan",
                        "worker_id": self.worker_id,
                        "stream_size": stream_size,
                        "pending_count": pending_count,
                        "unfinished_count": work.unfinished,
                        "retained_event_count": work.events,
                        "retained_delivery_count": work.deliveries,
                        "retained_receipt_count": work.receipts,
                        "retained_attempt_count": work.attempts,
                        "recovery_count": recovered,
                        "outcome": "stream_loss_reconciled"
                        if recovered
                        else "scan_complete",
                    },
                )
                backoff = self._initial_backoff()
                await self._wait(
                    stop, self.settings.event_worker_recovery_scan_interval_ms
                )
            except asyncio.CancelledError:
                raise
            except WorkerRedisFailure as error:
                self._log_redis_failure(
                    error, outcome="recovery_probe_deferred", consumer_name=None
                )
                await self._wait(stop, backoff)
                backoff = self._next_backoff(backoff)
            except SQLAlchemyError:
                self._log_database_failure(outcome="recovery_scan_paused")
                await self._wait(stop, backoff)
                backoff = self._next_backoff(backoff)
            except Exception:
                logger.error(
                    "event_worker_recovery_loop_failed",
                    extra={
                        "event": "worker_loop_failure",
                        "worker_id": self.worker_id,
                        "failure_category": "worker_internal",
                        "outcome": "recovery_paused",
                    },
                )
                await self._wait(stop, backoff)
                backoff = self._next_backoff(backoff)

    async def _consumer_loop(self, group: ConsumerName, stop: asyncio.Event) -> None:
        consumer = f"{self.worker_id}.{group}"
        cursor = "-"
        backoff = self._initial_backoff()
        while not stop.is_set():
            try:
                await self.streams.ensure_groups()
                pending = await self.streams.pending_page(
                    group,
                    cursor=cursor,
                    count=self.settings.event_worker_recovery_batch_size,
                )
                if pending:
                    cursor = f"({pending[-1].message_id}"
                    for message in await self._claim_abandoned(
                        pending, group=group, consumer=consumer
                    ):
                        await self._route_message(message, group)
                else:
                    cursor = "-"
                messages = await self.streams.read_new(
                    group,
                    consumer,
                    count=self.settings.event_worker_recovery_batch_size,
                    block_ms=self.settings.event_worker_redis_block_ms,
                )
                for message in messages:
                    await self._route_message(message, group)
                backoff = self._initial_backoff()
            except asyncio.CancelledError:
                raise
            except WorkerRedisFailure as error:
                self._log_redis_failure(
                    error,
                    outcome="consumer_probe_deferred",
                    consumer_name=group,
                )
                await self._wait(stop, backoff)
                backoff = self._next_backoff(backoff)
            except SQLAlchemyError:
                self._log_database_failure(
                    outcome="consumer_paused", consumer_name=group
                )
                await self._wait(stop, backoff)
                backoff = self._next_backoff(backoff)
            except Exception:
                logger.error(
                    "event_worker_consumer_loop_failed",
                    extra={
                        "event": "worker_loop_failure",
                        "worker_id": self.worker_id,
                        "consumer_name": group,
                        "failure_category": "worker_internal",
                        "outcome": "consumer_paused",
                    },
                )
                await self._wait(stop, backoff)
                backoff = self._next_backoff(backoff)

    async def _claim_abandoned(
        self,
        pending: list[PendingMessage],
        *,
        group: ConsumerName,
        consumer: str,
    ) -> list[StreamMessage]:
        abandoned = [
            message.message_id
            for message in pending
            if message.owner != consumer
            and message.idle_ms >= self.settings.event_worker_pending_idle_ms
        ]
        return await self.streams.claim_pending(
            group,
            consumer,
            min_idle_ms=self.settings.event_worker_pending_idle_ms,
            message_ids=abandoned,
        )

    async def _route_message(self, message: StreamMessage, group: ConsumerName) -> None:
        raw_event_id = message.fields.get("event_id")
        try:
            event_id = UUID(raw_event_id or "")
        except (ValueError, TypeError):
            self._log_bad_reference(message, group, "invalid_event_id")
            return
        try:
            stored = await load_stored_delivery(
                self.sessions, event_id=event_id, consumer_name=group
            )
        except ValueError:
            self._log_bad_reference(message, group, "invalid_stored_event")
            return
        if stored is None:
            self._log_bad_reference(message, group, "event_not_found")
            return
        event = stored.event
        if (
            message.fields.get("event_type") != event.event_type
            or message.fields.get("schema_version") != str(event.schema_version)
            or message.fields.get("correlation_id") != event.correlation_id
        ):
            self._log_bad_reference(message, group, "reference_conflict")
            return
        if group not in consumers_for(event.event_type):
            acknowledged = await self.streams.acknowledge(group, message.message_id)
            logger.info(
                "event_worker_unsubscribed_reference_acknowledged",
                extra={
                    "event": "worker_reference_routed",
                    "event_id": str(event.event_id),
                    "consumer_name": group,
                    "worker_id": self.worker_id,
                    "correlation_id": event.correlation_id,
                    "transport_message_id": message.message_id,
                    "outcome": "unsubscribed_acknowledged"
                    if acknowledged
                    else "already_acknowledged",
                },
            )
            return
        if stored.status is None:
            outcome = "subscribed_delivery_missing"
        elif not stored.is_due:
            outcome = "subscribed_delivery_not_due"
        elif stored.status == "succeeded" and stored.receipt_outcome is not None:
            acknowledged = await self.streams.acknowledge(group, message.message_id)
            outcome = (
                "durable_receipt_acknowledged"
                if acknowledged
                else "already_acknowledged"
            )
        elif stored.status == "failed":
            acknowledged = await self.streams.acknowledge(group, message.message_id)
            outcome = (
                "durable_failure_acknowledged"
                if acknowledged
                else "already_acknowledged"
            )
        elif stored.status == "succeeded":
            outcome = "success_without_receipt_retained"
        else:
            # Issue #35 owns effect+receipt orchestration. Keep subscribed work
            # in the PEL until that durable processing path is installed.
            outcome = "awaiting_consumer_execution"
        logger.info(
            "event_worker_subscribed_reference_retained",
            extra={
                "event": "worker_reference_routed",
                "event_id": str(event.event_id),
                "consumer_name": group,
                "worker_id": self.worker_id,
                "correlation_id": event.correlation_id,
                "transport_message_id": message.message_id,
                "outcome": outcome,
            },
        )

    def _log_bad_reference(
        self, message: StreamMessage, group: ConsumerName, category: str
    ) -> None:
        # The stream ID is safe transport metadata. Do not log untrusted fields.
        logger.warning(
            "event_worker_reference_rejected",
            extra={
                "event": "worker_reference_rejected",
                "consumer_name": group,
                "worker_id": self.worker_id,
                "transport_message_id": message.message_id,
                "failure_category": category,
                "outcome": "left_pending",
            },
        )
