"""Test-only real HTTP API paused immediately after order command commit."""

import asyncio
import json
import socket

import uvicorn

from app.main import app
from app.modules.orders.service import OrderService


async def main():
    original = OrderService.update

    async def paused(self, order_id, command):
        result = await original(self, order_id, command)
        if command.status == "ACCEPTED":
            print(json.dumps({"committed": order_id}), flush=True)
            # The parent terminates this process at this exact boundary. No
            # transport publisher or worker is installed in the API.
            await asyncio.Event().wait()
        return result

    OrderService.update = paused
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(15):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("API exited before startup")
                await asyncio.sleep(0.01)
        print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
        await task
    finally:
        listener.close()


if __name__ == "__main__":
    asyncio.run(main())
