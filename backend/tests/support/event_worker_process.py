"""Real worker process with deterministic test barriers at crash boundaries."""

import asyncio
import json
import os
import signal

from app.core.config import get_settings
from app.core.logging import configure_json_logging
from app.db.database import AsyncSessionLocal, engine
from app.modules.events.repo.worker_queries import DeliveryClaim
from app.modules.events.worker.runtime import EventWorker, WorkerHooks


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(_signum: int, _frame: object) -> None:
        loop.call_soon_threadsafe(stop.set)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signal_value = getattr(signal, name, None)
        if signal_value is not None:
            signal.signal(signal_value, request_stop)

    pause_at = os.environ.get("EVENT_WORKER_TEST_PAUSE_AT")

    async def pause(phase: str, event_id: object, claim_id: object) -> None:
        if pause_at == phase:
            print(
                json.dumps(
                    {
                        "phase": phase,
                        "event_id": str(event_id),
                        "claim_id": str(claim_id),
                    }
                ),
                flush=True,
            )
            await asyncio.Event().wait()

    async def after_claim(claim: DeliveryClaim) -> None:
        await pause("after_claim", claim.event_id, claim.claim_token)

    async def after_publish(claim: DeliveryClaim, _message_id: str) -> None:
        await pause("after_publish", claim.event_id, claim.claim_token)

    hooks = WorkerHooks(
        after_claim=after_claim if pause_at == "after_claim" else None,
        after_publish=after_publish if pause_at == "after_publish" else None,
    )
    settings = get_settings()
    configure_json_logging(level=settings.log_level)
    try:
        await EventWorker(settings, AsyncSessionLocal, hooks=hooks).run(stop)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
