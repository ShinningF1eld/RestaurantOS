"""Dedicated bounded Redis transport for the event worker process."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import (
    ConnectionError,
    InvalidResponse,
    RedisError,
    ResponseError,
    TimeoutError as RedisTimeout,
)

from app.core.config import Settings


class WorkerFailureKind(StrEnum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    COMMAND = "command"


class WorkerRedisFailure(Exception):
    """Safe transport category without the underlying driver text or URL."""

    def __init__(
        self, kind: WorkerFailureKind, *, server_code: str | None = None
    ) -> None:
        self.kind = kind
        self.server_code = server_code
        super().__init__(f"Worker Redis operation failed ({kind.value})")


class RedisClient(Protocol):
    async def execute_command(self, *args: object) -> object: ...
    def xpending_range(
        self,
        name: str,
        groupname: str,
        min: str,
        max: str,
        count: int,
        consumername: str | None = None,
        idle: int | None = None,
    ) -> Awaitable[object]: ...
    async def aclose(self) -> None: ...


def create_worker_client(settings: Settings) -> RedisClient:
    """Allocate an independent pool; do not inherit API transport budgets."""
    deadline = settings.event_worker_redis_operation_budget_ms / 1000
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=deadline,
        socket_timeout=deadline,
        max_connections=settings.event_worker_redis_max_connections,
        retry=Retry(NoBackoff(), 0),
        retry_on_error=[],
        decode_responses=True,
        health_check_interval=0,
    )


def _safe_server_code(error: ResponseError) -> str | None:
    """Keep only a small Redis protocol code allowlist, never error details."""
    try:
        code = str(error).split(maxsplit=1)[0].upper()
    except Exception:
        return None
    return code if code in {"BUSYGROUP", "NOGROUP", "WRONGTYPE", "ERR"} else None


class WorkerRedisTransport:
    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[[Settings], RedisClient] = create_worker_client,
    ) -> None:
        self._settings = settings
        self._factory = client_factory
        self._client: RedisClient | None = None

    @property
    def settings(self) -> Settings:
        return self._settings

    async def open(self) -> None:
        """Create the bounded pool without connecting or pinging Redis."""
        if self._client is None:
            self._client = self._factory(self._settings)

    async def _bounded(self, operation: Callable[[], Awaitable[object]]) -> object:
        try:
            async with asyncio.timeout(
                self._settings.event_worker_redis_operation_budget_ms / 1000
            ):
                return await operation()
        except (TimeoutError, RedisTimeout):
            failure = WorkerRedisFailure(WorkerFailureKind.TIMEOUT)
        except (ConnectionError, InvalidResponse, OSError):
            failure = WorkerRedisFailure(WorkerFailureKind.CONNECTION)
        except ResponseError as error:
            failure = WorkerRedisFailure(
                WorkerFailureKind.COMMAND, server_code=_safe_server_code(error)
            )
        except RedisError:
            failure = WorkerRedisFailure(WorkerFailureKind.COMMAND)
        raise failure from None

    async def execute(self, *arguments: object) -> object:
        client = self._client
        if client is None:
            raise WorkerRedisFailure(WorkerFailureKind.CONNECTION)
        return await self._bounded(lambda: client.execute_command(*arguments))

    async def pending_range(
        self,
        stream: str,
        group: str,
        start: str,
        end: str,
        count: int,
    ) -> object:
        """Use redis-py's ranged response parser for XPENDING detail rows."""
        client = self._client
        if client is None:
            raise WorkerRedisFailure(WorkerFailureKind.CONNECTION)
        return await self._bounded(
            lambda: client.xpending_range(stream, group, start, end, count)
        )

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await self._bounded(client.aclose)

    def stream_key(self) -> str:
        return self._settings_namespace() + "stream"

    def _settings_namespace(self) -> str:
        environment = self._settings.environment
        prefix = f"restaurantos:{environment}"
        if environment == "test":
            prefix += f":{self._settings.redis_test_namespace}"
        return f"{prefix}:events:v1:"
