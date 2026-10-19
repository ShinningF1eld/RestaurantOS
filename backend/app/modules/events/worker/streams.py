"""Redis 7 Streams commands and fixed-group routing primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from app.modules.events.domain.contracts import ConsumerName
from app.modules.events.domain.subscriptions import SUBSCRIPTIONS
from app.modules.events.repo.worker_queries import DeliveryClaim
from app.modules.events.worker.redis import (
    WorkerRedisFailure,
    WorkerRedisTransport,
)


GROUPS: tuple[ConsumerName, ...] = ("analytics", "alerts", "notification_sink")


@dataclass(frozen=True, slots=True)
class StreamMessage:
    message_id: str
    fields: dict[str, str]


@dataclass(frozen=True, slots=True)
class PendingMessage:
    message_id: str
    owner: str
    idle_ms: int


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    if isinstance(value, str):
        return value
    return str(value)


def _mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {_text(key): item for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        items = list(value)
        return {
            _text(items[index]): items[index + 1]
            for index in range(0, len(items) - 1, 2)
        }
    return {}


def _stream_messages(result: object) -> list[StreamMessage]:
    if not isinstance(result, (list, tuple)):
        return []
    messages: list[StreamMessage] = []
    for stream in result:
        if not isinstance(stream, (list, tuple)) or len(stream) != 2:
            continue
        entries = stream[1]
        if not isinstance(entries, (list, tuple)):
            continue
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            message_id, values = entry
            fields = _mapping(values)
            messages.append(
                StreamMessage(
                    message_id=_text(message_id),
                    fields={key: _text(value) for key, value in fields.items()},
                )
            )
    return messages


def _claimed_messages(result: object) -> list[StreamMessage]:
    if not isinstance(result, (list, tuple)):
        return []
    messages: list[StreamMessage] = []
    for entry in result:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        message_id, values = entry
        fields = _mapping(values)
        messages.append(
            StreamMessage(
                message_id=_text(message_id),
                fields={key: _text(value) for key, value in fields.items()},
            )
        )
    return messages


def _group_names(result: object) -> set[str]:
    if not isinstance(result, (list, tuple)):
        return set()
    names: set[str] = set()
    for row in result:
        name = _mapping(row).get("name")
        if name is not None:
            names.add(_text(name))
    return names


def _group_pending_counts(result: object) -> dict[str, int]:
    if not isinstance(result, (list, tuple)):
        return {}
    pending: dict[str, int] = {}
    for row in result:
        value = _mapping(row)
        name = value.get("name")
        count = value.get("pending")
        if name is None or count is None:
            continue
        try:
            pending[_text(name)] = int(cast(str | bytes | int, count))
        except (TypeError, ValueError):
            continue
    return pending


def _pending_messages(result: object) -> list[PendingMessage]:
    if not isinstance(result, (list, tuple)):
        return []
    pending: list[PendingMessage] = []
    for row in result:
        if isinstance(row, dict):
            value = _mapping(row)
            message_id = value.get("message_id")
            owner = value.get("consumer")
            idle = value.get("time_since_delivered")
        elif isinstance(row, (list, tuple)) and len(row) >= 4:
            message_id, owner, idle = row[0], row[1], row[2]
        else:
            continue
        if message_id is None or owner is None or idle is None:
            continue
        try:
            idle_ms = int(cast(str | bytes | int, idle))
        except (TypeError, ValueError):
            continue
        pending.append(
            PendingMessage(
                message_id=_text(message_id), owner=_text(owner), idle_ms=idle_ms
            )
        )
    return pending


class EventStreams:
    """One stream shared by independent groups derived from the fixed registry."""

    def __init__(self, redis: WorkerRedisTransport) -> None:
        self._redis = redis
        self.stream = redis.stream_key()
        registered = {
            consumer for consumers in SUBSCRIPTIONS.values() for consumer in consumers
        }
        if registered != set(GROUPS):
            raise RuntimeError("Event consumer groups do not match the fixed registry")

    async def ensure_groups(self) -> bool:
        """Create absent groups from the stream start, preserving existing groups.

        Return whether the stream existed before this call. A zero-length stream
        after Redis content loss is separately reconciled from PostgreSQL.
        """
        existed = bool(await self._redis.execute("EXISTS", self.stream))
        group_names = (
            _group_names(await self._redis.execute("XINFO", "GROUPS", self.stream))
            if existed
            else set()
        )
        for group in GROUPS:
            if group in group_names:
                continue
            try:
                await self._redis.execute(
                    "XGROUP", "CREATE", self.stream, group, "0-0", "MKSTREAM"
                )
            except WorkerRedisFailure as error:
                if error.server_code != "BUSYGROUP":
                    raise
        return existed

    async def publish(self, claim: DeliveryClaim) -> str:
        """Add only stable identity and allowlisted routing/correlation metadata."""
        result = await self._redis.execute(
            "XADD",
            self.stream,
            "*",
            "event_id",
            str(claim.event_id),
            "event_type",
            claim.event_type,
            "schema_version",
            str(claim.schema_version),
            "correlation_id",
            claim.correlation_id,
        )
        return _text(result)

    async def read_new(
        self, group: ConsumerName, consumer: str, *, count: int, block_ms: int
    ) -> list[StreamMessage]:
        result = await self._redis.execute(
            "XREADGROUP",
            "GROUP",
            group,
            consumer,
            "COUNT",
            count,
            *(["BLOCK", block_ms] if block_ms > 0 else []),
            "STREAMS",
            self.stream,
            ">",
        )
        return _stream_messages(result)

    async def pending_page(
        self, group: ConsumerName, *, cursor: str, count: int
    ) -> list[PendingMessage]:
        result = await self._redis.pending_range(self.stream, group, cursor, "+", count)
        return _pending_messages(result)

    async def pending_reference(
        self, group: ConsumerName, consumer: str, message_id: str
    ) -> StreamMessage | None:
        """Reload one PEL entry only while this consumer still owns it."""
        pending = _pending_messages(
            await self._redis.pending_range(
                self.stream, group, message_id, message_id, 1
            )
        )
        if not pending or pending[0].owner != consumer:
            return None
        entries = await self._redis.execute(
            "XRANGE", self.stream, message_id, message_id, "COUNT", 1
        )
        messages = _claimed_messages(entries)
        return messages[0] if messages else None

    async def claim_pending(
        self,
        group: ConsumerName,
        consumer: str,
        *,
        min_idle_ms: int,
        message_ids: list[str],
    ) -> list[StreamMessage]:
        if not message_ids:
            return []
        result = await self._redis.execute(
            "XCLAIM",
            self.stream,
            group,
            consumer,
            min_idle_ms,
            *message_ids,
        )
        return _claimed_messages(result)

    async def acknowledge(self, group: ConsumerName, message_id: str) -> bool:
        result = await self._redis.execute("XACK", self.stream, group, message_id)
        return int(cast(int | str, result)) > 0

    async def length(self) -> int:
        result = await self._redis.execute("XLEN", self.stream)
        return int(cast(int | str, result))

    async def pending_count(self, group: ConsumerName) -> int:
        result = await self._redis.execute("XINFO", "GROUPS", self.stream)
        return _group_pending_counts(result).get(group, 0)
