"""No detached auth task: cancellation unwinds the owned transaction stack."""

import asyncio
import logging
import os
from time import monotonic
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.modules.auth.domain.errors import AuthStorageError

AUTH_OPERATION_SECONDS = 8
create_timeout = asyncio.timeout


@dataclass
class AuthenticationDeadline:
    expires: float
    commit_started: bool = False
    commit_finished: bool = False

    def check(self) -> None:
        if monotonic() >= self.expires:
            raise TimeoutError()


@asynccontextmanager
async def authentication_deadline() -> AsyncIterator[AuthenticationDeadline]:
    operation = AuthenticationDeadline(monotonic() + AUTH_OPERATION_SECONDS)
    try:
        async with create_timeout(AUTH_OPERATION_SECONDS):
            try:
                yield operation
            finally:
                operation.check()
    except (TimeoutError, asyncio.CancelledError) as error:
        logging.getLogger(__name__).warning(
            "Authentication operation abandoned",
            extra={
                "event": "auth_commit_uncertain"
                if operation.commit_started and not operation.commit_finished
                else "auth_operation_abandoned",
                "reason": "deadline"
                if isinstance(error, TimeoutError)
                else "cancelled",
                "process_id": os.getpid(),
            },
        )
        # A live caller receives the same retryable server response for timeout
        # or cancellation. A disconnected/cancelled transport may send nothing.
        raise AuthStorageError() from None
