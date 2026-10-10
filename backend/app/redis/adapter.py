"""Reusable async transport with one deadline and no business health state."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.maint_notifications import MaintNotificationsConfig
from redis.exceptions import (
    ConnectionError,
    InvalidResponse,
    RedisError,
    TimeoutError as RedisTimeout,
)

from app.core.config import Settings


class FailureKind(StrEnum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    COMMAND = "command"
    CLOSED = "closed"


class RedisFailure(Exception):
    """Safe category only: never retains driver messages, URLs, keys or payloads.

    A timeout/connection failure may follow a completed write. Callers own replay
    semantics and must not blindly retry ambiguous non-idempotent operations.
    COMMAND covers server rejection, not malformed application payloads.
    """

    def __init__(self, kind: FailureKind) -> None:
        self.kind = kind
        super().__init__(f"Redis operation failed ({kind.value})")


class AsyncRedisClient(Protocol):
    async def execute_command(self, *args: object) -> object: ...
    async def aclose(self) -> None: ...


def create_client(settings: Settings) -> AsyncRedisClient:
    # URL query options are forbidden in Settings: from_url query parameters
    # otherwise override these safety settings. Construction performs no I/O.
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=settings.redis_operation_budget_ms / 1000,
        socket_timeout=settings.redis_operation_budget_ms / 1000,
        max_connections=settings.redis_max_connections,
        retry=Retry(NoBackoff(), 0),
        retry_on_error=[],
        decode_responses=False,
        health_check_interval=0,
        maint_notifications_config=MaintNotificationsConfig(enabled=False),
    )


class RedisAdapter:
    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[[Settings], AsyncRedisClient] = create_client,
    ) -> None:
        self._settings = settings
        self._factory = client_factory
        self._client: AsyncRedisClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def open(self) -> None:
        """Allocate once without PING/connect; an outage never blocks startup."""
        if self._client is None:
            self._client = self._factory(self._settings)
            self._loop = asyncio.get_running_loop()

    def owns_current_loop(self) -> bool:
        return self._client is not None and self._loop is asyncio.get_running_loop()

    async def _bounded(self, operation: Callable[[], Awaitable[object]]) -> object:
        failure: FailureKind
        try:
            # Includes pool acquisition, DNS/connect, command and reply. Socket
            # timeouts are secondary guards, never additive operation budgets.
            async with asyncio.timeout(self._settings.redis_operation_budget_ms / 1000):
                return await operation()
        except (TimeoutError, RedisTimeout):
            failure = FailureKind.TIMEOUT
        except (ConnectionError, InvalidResponse, OSError):
            failure = FailureKind.CONNECTION
        except RedisError:
            failure = FailureKind.COMMAND
        # Raise outside the handler so traceback context cannot leak driver data.
        # Cancellation propagates unchanged. No logs contain command arguments.
        raise RedisFailure(failure)

    async def execute(self, *arguments: object) -> object:
        """Execute one low-level command; bytes/None remain normal data results."""
        client = self._client
        if client is None:
            raise RedisFailure(FailureKind.CLOSED)
        return await self._bounded(lambda: client.execute_command(*arguments))

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await self._bounded(client.aclose)

    def namespace(self, use_case: str, version: int) -> str:
        """Return a prefix only; callers supply safe IDs/HMACs, never raw PII."""
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", use_case) or version < 1:
            raise ValueError("Invalid Redis namespace")
        environment = self._settings.environment
        prefix = f"restaurantos:{environment}"
        if environment == "test":
            prefix += f":{self._settings.redis_test_namespace}"
        return f"{prefix}:{use_case}:v{version}:"
