"""Consumer-owned atomic effects, receipts, persisted attempts, and fencing.

Handlers are trusted, transaction-bound feature interfaces: no commits or network
I/O. The service owns their transaction. Payloads never choose executable code.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.exc import DBAPIError, IntegrityError, TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.analytics.service import apply_order_event

from app.modules.events.domain.contracts import (
    ConsumerName,
    EventEnvelope,
    UnsupportedEventVersion,
    deserialize_event,
)
from app.modules.events.domain.diagnostics import safe_identifier
from app.modules.events.domain.retries import RetryPolicy
from app.modules.events.domain.subscriptions import consumers_for
from app.modules.events.repo import delivery_queries as queries
from app.modules.events.repo.models import (
    EventDelivery,
    EventDeliveryAttempt,
    EventReceipt,
    OutboxEvent,
)


Effect = Callable[
    [AsyncSession, EventEnvelope], Awaitable[Literal["processed", "skipped"]]
]
# Issues #36–37 install actual feature interfaces here. Missing implementations
# must never write placeholder receipts or consume the poison-event allowance.
CONSUMERS: Mapping[ConsumerName, Effect | None] = MappingProxyType(
    {
        "analytics": apply_order_event,
        "alerts": None,
        "notification_sink": None,
    }
)
logger = logging.getLogger("restaurantos.event_consumer")


class DependencyUnavailable(Exception):
    """A trusted handler reports a shared dependency outage, without details."""


class EventTransientFailure(Exception):
    """An event-specific failure that may recover on a later attempt."""


@dataclass(frozen=True, slots=True)
class Failure:
    category: str
    infrastructure: bool = False
    permanent: bool = False


def classify_failure(error: Exception) -> Failure:
    if isinstance(error, DependencyUnavailable):
        return Failure("dependency_unavailable", infrastructure=True)
    if isinstance(error, (PoolTimeout, OSError, TimeoutError)):
        return Failure("postgres_unavailable", infrastructure=True)
    original = error.orig if isinstance(error, DBAPIError) else error
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if (isinstance(error, DBAPIError) and error.connection_invalidated) or (
        isinstance(code, str)
        and (
            code.startswith(("08", "28", "53"))
            or code in {"57P01", "57P02", "57P03", "58030"}
        )
    ):
        return Failure("postgres_unavailable", infrastructure=True)
    if isinstance(error, IntegrityError) or (
        isinstance(code, str) and code.startswith("23")
    ):
        return Failure("event_constraint", permanent=True)
    if code in {"40001", "40P01"}:
        return Failure("event_transient")
    if isinstance(error, EventTransientFailure):
        return Failure("event_transient")
    return Failure("handler_failure")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    outcome: str
    acknowledge: bool = False
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class AttemptClaim:
    event: EventEnvelope
    consumer: ConsumerName
    token: UUID
    attempt_id: UUID
    attempt_number: int
    retry_cycle: int
    replay_id: UUID | None


@dataclass(frozen=True, slots=True)
class ExecutionHooks:
    after_start: Callable[[AttemptClaim], Awaitable[None]] | None = None
    before_commit: Callable[[AttemptClaim], Awaitable[None]] | None = None
    after_commit: Callable[[AttemptClaim], Awaitable[None]] | None = None


class ConsumerExecutionService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        registry: Mapping[ConsumerName, Effect | None] = CONSUMERS,
        policy: RetryPolicy = RetryPolicy(),
        lease_seconds: int = 30,
        infrastructure_delay_seconds: float = 1,
        jitter: Callable[[], float] = random.random,
        clock: Callable[[], datetime] | None = None,
        hooks: ExecutionHooks = ExecutionHooks(),
    ) -> None:
        if set(registry) != set(CONSUMERS):
            raise ValueError(
                "Consumer registry must contain exactly the fixed consumers"
            )
        self.sessions = sessions
        self.registry = MappingProxyType(dict(registry))
        self.policy = policy
        self.lease_seconds = lease_seconds
        self.infrastructure_delay_seconds = infrastructure_delay_seconds
        self.jitter = jitter
        self.clock = clock
        self.hooks = hooks
        self._unsettled: dict[UUID, tuple[AttemptClaim, Failure]] = {}

    async def _now(self, session: AsyncSession) -> datetime:
        return self.clock() if self.clock else await queries.clock(session)

    @staticmethod
    def _clear_claim(delivery: EventDelivery) -> None:
        delivery.claim_token = None
        delivery.claim_owner = None
        delivery.claimed_at = None
        delivery.claim_expires_at = None

    def _log(
        self, claim: AttemptClaim, outcome: str, category: str | None = None
    ) -> None:
        logger.info(
            "event_consumer_attempt",
            extra={
                "event": "consumer_attempt",
                "event_id": str(claim.event.event_id),
                "consumer_name": claim.consumer,
                "correlation_id": claim.event.correlation_id,
                "attempt_id": str(claim.attempt_id),
                "attempt_number": claim.attempt_number,
                "retry_cycle": claim.retry_cycle,
                "replay_id": str(claim.replay_id) if claim.replay_id else None,
                "outcome": outcome,
                "failure_category": category,
            },
        )

    async def execute(
        self,
        *,
        event_id: UUID,
        consumer: ConsumerName,
        reference: Mapping[str, str],
        worker_id: str,
    ) -> ExecutionResult:
        await self.settle_failures()
        started = await self._start(event_id, consumer, reference, worker_id)
        if isinstance(started, ExecutionResult):
            return started
        claim = started
        self._log(claim, "started")
        if self.hooks.after_start:
            await self.hooks.after_start(claim)
        try:
            result = await self._effect(claim)
        except Exception as error:
            failure = classify_failure(error)
            # This session is independent of the rolled-back effect transaction.
            # If PostgreSQL itself is unavailable, the running claim survives and
            # recovery will fence it. No uncommitted effect can become visible.
            self._unsettled[claim.attempt_id] = (claim, failure)
            result = await self._finish_failure(claim, failure)
            self._unsettled.pop(claim.attempt_id, None)
            self._log(claim, result.outcome, failure.category)
            if failure.infrastructure:
                raise DependencyUnavailable() from None
            return result
        self._log(claim, result.outcome)
        if result.acknowledge and self.hooks.after_commit:
            await self.hooks.after_commit(claim)
        return result

    async def _start(
        self,
        event_id: UUID,
        consumer: ConsumerName,
        reference: Mapping[str, str],
        worker_id: str,
    ) -> AttemptClaim | ExecutionResult:
        async with self.sessions() as session, session.begin():
            event = await session.get(OutboxEvent, event_id)
            if event is None:
                return ExecutionResult("event_not_found")
            if any(
                reference.get(key) != str(getattr(event, key))
                for key in (
                    "event_id",
                    "event_type",
                    "schema_version",
                    "correlation_id",
                )
            ):
                return ExecutionResult("reference_conflict")
            correlation = safe_identifier(event.correlation_id)
            delivery = await queries.lock_delivery(
                session, event_id, consumer, skip_locked=True
            )
            if delivery is None:
                # Unknown contracts with an existing delivery are validated below;
                # only a known, non-subscribed route can be ACKed here.
                try:
                    unsubscribed = consumer not in consumers_for(event.event_type)  # type: ignore[arg-type]
                except (KeyError, ValueError):
                    unsubscribed = False
                return ExecutionResult(
                    "unsubscribed_acknowledged"
                    if unsubscribed
                    else "delivery_missing_or_busy",
                    unsubscribed,
                    correlation,
                )
            receipt = await queries.receipt(session, event_id, consumer)
            if receipt is not None and delivery.status == "succeeded":
                return ExecutionResult(
                    "durable_receipt_acknowledged", True, correlation
                )
            if delivery.status == "failed":
                return ExecutionResult(
                    "durable_failure_acknowledged", True, correlation
                )
            if delivery.status == "succeeded" or receipt is not None:
                return ExecutionResult(
                    "inconsistent_receipt_retained", False, correlation
                )
            now = await self._now(session)
            if delivery.next_attempt_at > now:
                return ExecutionResult(
                    "subscribed_delivery_not_due", False, correlation
                )
            if delivery.status == "processing":
                if (
                    delivery.claim_expires_at is not None
                    and delivery.claim_expires_at > now
                ):
                    return ExecutionResult("consumer_claim_active", False, correlation)
                for attempt in await queries.running_attempts(session, delivery.id):
                    attempt.status = "failed"
                    attempt.error_category = "worker_interrupted"
                    attempt.finished_at = now
                delivery.status = "pending"
                self._clear_claim(delivery)
                if delivery.attempt_count >= self.policy.max_attempts:
                    delivery.status = "failed"
                    delivery.last_error_category = "attempt_limit"
                    return ExecutionResult(
                        "durable_failure_acknowledged", True, correlation
                    )
            failure_category = None
            envelope = None
            try:
                envelope = deserialize_event(queries.event_facts(event))
            except UnsupportedEventVersion:
                failure_category = "unsupported_version"
            except ValueError:
                failure_category = "invalid_payload"
            if envelope is not None and consumer not in consumers_for(
                envelope.event_type
            ):
                return ExecutionResult("subscription_conflict", False, correlation)
            if failure_category is None and self.registry[consumer] is None:
                return ExecutionResult("handler_unavailable", False, correlation)
            if delivery.attempt_count >= self.policy.max_attempts:
                delivery.status = "failed"
                delivery.last_error_category = "attempt_limit"
                self._clear_claim(delivery)
                return ExecutionResult(
                    "durable_failure_acknowledged", True, correlation
                )
            token = uuid4()
            attempt = EventDeliveryAttempt(
                delivery_id=delivery.id,
                retry_cycle=delivery.retry_cycle,
                attempt_number=await queries.next_attempt_number(session, delivery),
                claim_token=token,
                started_at=now,
                status="failed" if failure_category else "running",
                finished_at=now if failure_category else None,
                error_category=failure_category,
            )
            session.add(attempt)
            delivery.attempt_count += 1
            delivery.status = "failed" if failure_category else "processing"
            delivery.last_error_category = failure_category
            delivery.claim_token = token
            delivery.claim_owner = worker_id
            delivery.claimed_at = now
            delivery.claim_expires_at = now + timedelta(seconds=self.lease_seconds)
            await session.flush()
            if failure_category:
                logger.info(
                    "event_consumer_contract_rejected",
                    extra={
                        "event": "consumer_attempt",
                        "event_id": str(event_id),
                        "consumer_name": consumer,
                        "correlation_id": correlation,
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "retry_cycle": delivery.retry_cycle,
                        "replay_id": str(replay_id)
                        if (
                            replay_id := await queries.replay_identity(
                                session, delivery
                            )
                        )
                        else None,
                        "failure_category": failure_category,
                        "outcome": "failed",
                    },
                )
                self._clear_claim(delivery)
                return ExecutionResult(failure_category, True, correlation)
            assert envelope is not None
            return AttemptClaim(
                envelope,
                consumer,
                token,
                attempt.id,
                attempt.attempt_number,
                delivery.retry_cycle,
                await queries.replay_identity(session, delivery),
            )

    async def _effect(self, claim: AttemptClaim) -> ExecutionResult:
        async with self.sessions() as session, session.begin():
            delivery = await queries.lock_delivery(
                session, claim.event.event_id, claim.consumer
            )
            if (
                delivery is None
                or delivery.status != "processing"
                or delivery.claim_token != claim.token
            ):
                return ExecutionResult("claim_superseded")
            now = await self._now(session)
            if delivery.claim_expires_at is None or delivery.claim_expires_at <= now:
                return ExecutionResult("claim_expired")
            handler = self.registry[claim.consumer]
            assert handler is not None
            outcome = await handler(session, claim.event)
            if outcome not in ("processed", "skipped"):
                raise ValueError("Handler must return a durable outcome")
            session.add(
                EventReceipt(
                    consumer_name=claim.consumer,
                    event_id=claim.event.event_id,
                    outcome=outcome,
                    processed_at=await self._now(session),
                )
            )
            delivery.status = "succeeded"
            delivery.last_error_category = None
            self._clear_claim(delivery)
            attempt = await session.get(EventDeliveryAttempt, claim.attempt_id)
            assert attempt is not None
            attempt.status = "skipped" if outcome == "skipped" else "succeeded"
            attempt.finished_at = await self._now(session)
            await session.flush()
            if self.hooks.before_commit:
                await self.hooks.before_commit(claim)
        return ExecutionResult("consumer_committed", True, claim.event.correlation_id)

    async def _finish_failure(
        self, claim: AttemptClaim, failure: Failure
    ) -> ExecutionResult:
        async with self.sessions() as session, session.begin():
            delivery = await queries.lock_delivery(
                session, claim.event.event_id, claim.consumer
            )
            if (
                delivery is None
                or delivery.status != "processing"
                or delivery.claim_token != claim.token
            ):
                return ExecutionResult("claim_superseded")
            now = await self._now(session)
            attempt = await session.get(EventDeliveryAttempt, claim.attempt_id)
            assert attempt is not None
            attempt.status = "failed"
            attempt.error_category = failure.category
            attempt.finished_at = now
            if failure.infrastructure:
                delivery.attempt_count -= 1
            terminal = failure.permanent or (
                not failure.infrastructure
                and delivery.attempt_count >= self.policy.max_attempts
            )
            delivery.status = "failed" if terminal else "pending"
            delivery.last_error_category = failure.category
            delay = (
                self.infrastructure_delay_seconds
                if failure.infrastructure
                else self.policy.delay_seconds(delivery.attempt_count, self.jitter())
            )
            delivery.next_attempt_at = now + timedelta(seconds=delay)
            delivery.published_at = None
            self._clear_claim(delivery)
        return ExecutionResult(
            "consumer_failed" if terminal else "consumer_retry_scheduled",
            terminal,
            claim.event.correlation_id,
        )

    async def settle_failures(self) -> None:
        # Preserve classification while this process reconnects to PostgreSQL.
        # There is at most one unsettled attempt per sequential consumer loop.
        for attempt_id, (claim, failure) in tuple(self._unsettled.items()):
            await self._finish_failure(claim, failure)
            self._unsettled.pop(attempt_id, None)

    async def recover_expired(self, *, limit: int) -> int:
        """Recover dead processes even when every Redis reference has been lost."""
        from sqlalchemy import select

        await self.settle_failures()
        async with self.sessions() as session, session.begin():
            now = await self._now(session)
            rows = list(
                await session.scalars(
                    select(EventDelivery)
                    .where(
                        EventDelivery.status == "processing",
                        EventDelivery.claim_expires_at <= now,
                    )
                    .order_by(EventDelivery.claim_expires_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            for delivery in rows:
                for attempt in await queries.running_attempts(session, delivery.id):
                    attempt.status = "failed"
                    attempt.error_category = "worker_interrupted"
                    attempt.finished_at = now
                delivery.status = (
                    "failed"
                    if delivery.attempt_count >= self.policy.max_attempts
                    else "pending"
                )
                delivery.last_error_category = "worker_interrupted"
                delivery.next_attempt_at = now
                delivery.published_at = None
                self._clear_claim(delivery)
            return len(rows)
