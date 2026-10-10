"""Disposable nonpersistent Redis with a port that survives physical restart."""

import socket
import subprocess
import time
from contextlib import contextmanager
from uuid import uuid4


def docker(*arguments):
    return subprocess.check_output(
        ["docker", *arguments], text=True, timeout=45
    ).strip()


@contextmanager
def owned_redis():
    name = "restaurantos-auth-outage-" + uuid4().hex[:12]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"127.0.0.1:{port}:6379",
            "redis:7-alpine",
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        )
        assert int(docker("port", name, "6379/tcp").rsplit(":", 1)[1]) == port
        for attempt in range(50):
            if docker("exec", name, "redis-cli", "ping") == "PONG":
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Owned Redis did not become ready")
        yield name, str(port)
    finally:
        docker("rm", "-f", name)
