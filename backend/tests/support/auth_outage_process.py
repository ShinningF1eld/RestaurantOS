"""Test-owned API process; control clocks via stdin, never production endpoints."""

import asyncio
import json
import socket
import sys

import uvicorn

from app.main import app, settings, auth_redis
from app.modules.auth.rate_limit import AuthLimiter, install_limiter


async def main():
    clock = [1.0]
    subject = AuthLimiter(
        settings, auth_redis, monotonic=lambda: clock[0], wall=lambda: clock[0]
    )
    app.state.auth_limiter = subject
    install_limiter(subject)
    # Count attempted application commands, including failures, without keys.
    from app.redis.adapter import RedisAdapter

    commands = [0]
    execute = RedisAdapter.execute

    async def counted(self, *args):
        commands[0] += 1
        return await execute(self, *args)

    RedisAdapter.execute = counted
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(
        uvicorn.Config(app, log_config=None, access_log=False, lifespan="on")
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))

    def emit(value):
        print(json.dumps(value), flush=True)

    try:
        async with asyncio.timeout(15):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("API exited before startup")
                await asyncio.sleep(0.01)
        emit({"port": listener.getsockname()[1]})
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
            command = json.loads(line)
            if command["op"] == "stop":
                break
            if command["op"] == "advance":
                clock[0] += command["seconds"]
            emit(
                {
                    "commands": commands[0],
                    "entries": len(subject._entries),
                    "failures": sum(len(e.failures) for e in subject._entries.values()),
                    "degraded": subject._degraded_at is not None,
                    "successes": subject._successes,
                }
            )
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 15)
        listener.close()


if __name__ == "__main__":
    asyncio.run(main())
