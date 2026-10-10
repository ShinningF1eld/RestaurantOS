"""Physical isolated Redis loss/restart and two real API processes over HTTP."""

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import text

from conftest import engine
from support.owned_redis import docker, owned_redis

BACKEND = Path(__file__).resolve().parents[3]
HEADERS = {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}


class Api:
    def __init__(self, env, log):
        self.log = log.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, str(BACKEND / "tests/support/auth_outage_process.py")],
            cwd=BACKEND,
            env={**env, "PYTHONPATH": str(BACKEND)},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            bufsize=1,
        )
        self.messages = queue.Queue()

        def read():
            for line in self.process.stdout:
                self.messages.put(line)
            self.messages.put(None)

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            self.port = self.receive()["port"]
        except BaseException:
            self.close()
            raise

    def receive(self):
        line = self.messages.get(timeout=25)
        if line is None:
            raise RuntimeError("Test API process exited; inspect its safe log")
        return json.loads(line)

    def control(self, op="state", **fields):
        self.process.stdin.write(json.dumps({"op": op, **fields}) + "\n")
        self.process.stdin.flush()
        return self.receive()

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.stdin.write('{"op":"stop"}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=20)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=10)
            self.reader.join(timeout=2)
            for stream in (self.process.stdin, self.process.stdout, self.log):
                stream.close()

    def client(self):
        return httpx.Client(
            base_url=f"http://127.0.0.1:{self.port}", headers=HEADERS, timeout=12
        )


def login(
    client,
    email="absent@example.test",
    password="invalid password for test",  # pragma: allowlist secret
):
    return client.post("/auth/login", json={"email": email, "password": password})


def limited(response):
    assert response.status_code == 429
    assert response.json() == {"detail": "Too many attempts"}
    assert int(response.headers["retry-after"]) > 0


def recover_to(api, client, target):
    # A restarted Redis can still time out reconnecting a stale pool connection.
    # Failed probes must reset stability; only consecutive real successes count.
    for _ in range(10):
        api.control("advance", seconds=5)
        limited(login(client))
        state = api.control()
        assert state["degraded"] == (state["successes"] != 3)
        if state["successes"] == target:
            return
    raise AssertionError("Limiter did not recover on isolated restarted Redis")


def test_physical_outage_flapping_two_api_processes_and_process_restart(
    tmp_path, auth_user
):
    with owned_redis() as (redis, port):
        env = {
            **os.environ,
            "REDIS_URL": f"redis://127.0.0.1:{port}/0",
            "REDIS_TEST_NAMESPACE": "outage-" + uuid4().hex,
            "AUTH_LOCAL_MAX_ENTRIES": "8",
        }
        processes = []

        def start(label):
            api = Api(env, tmp_path / (label + ".log"))
            processes.append(api)
            return api

        try:
            first, second = start("first"), start("second")
            with first.client() as a, second.client() as b:
                assert login(a).status_code == 401
                # Both processes use the same shared normal quota.
                assert login(b).status_code == 401
                for client in (a, b, a):
                    assert login(client).status_code == 401
                limited(login(b))
                assert not first.control()["degraded"]
                valid = login(a, auth_user["email"], auth_user["password"])
                assert valid.status_code == 200
                docker("stop", "--time", "0", redis)
                for client, api in ((a, first), (b, second)):
                    for _ in range(3):
                        assert login(client).status_code == 401
                    before = api.control()["commands"]
                    limited(login(client))
                    assert api.control()["commands"] == before
                    assert client.get("/health").status_code == 200
                # Existing access cookie remains usable; outage refresh rotations
                # charge the known family five times, then throttle generically.
                assert a.get("/auth/me").status_code == 200
                for _ in range(5):
                    assert a.post("/auth/refresh").status_code == 200
                limited(a.post("/auth/refresh"))
                assert a.get("/auth/me").status_code == 200
                # Eight active entries: login pair/IP, refresh family/IP, four
                # new pairs. Capacity rejection preserves all live counters.
                for i in range(4):
                    assert login(a, f"other{i}@example.test").status_code == 401
                assert first.control()["entries"] == 8
                limited(login(a, "overflow@example.test"))
                assert first.control()["entries"] == 8
                before = first.control()["commands"]
                for _ in range(5):
                    limited(login(a))
                assert first.control()["commands"] == before
                # A restarted process loses local history; the other stays full.
                second.close()
                restarted = start("restarted")
                with restarted.client() as c:
                    assert login(c).status_code == 401
                    limited(login(a))
                docker("start", redis)
                assert docker("exec", redis, "redis-cli", "ping") == "PONG"
                recover_to(first, a, 1)
                docker("stop", "--time", "0", redis)
                first.control("advance", seconds=5)
                limited(login(a))
                assert first.control()["successes"] == 0
                docker("start", redis)
                assert docker("exec", redis, "redis-cli", "ping") == "PONG"
                for expected in (1, 2, 3):
                    recover_to(first, a, expected)
                # A new pair still guards the surviving local IP history.
                assert login(a, "fresh@example.test").status_code == 401
                first.control("advance", seconds=900)
                assert login(a).status_code == 401
                assert first.control()["entries"] == 0
                # Shared Redis itself lost old counters on nonpersistent restart.
                with restarted.client() as c:
                    restarted.control("advance", seconds=5)
                    assert login(c, "postrestart@example.test").status_code == 401
            with engine.begin() as connection:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM auth_rate_limit_buckets")
                    ).scalar_one()
                    == 0
                )
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM auth_sessions")
                    ).scalar_one()
                    > 0
                )
        finally:
            for api in reversed(processes):
                if not api.log.closed:
                    api.close()
        events = []
        for line in (tmp_path / "first.log").read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event", "").startswith("auth_limiter_"):
                events.append(event)
        names = [e["event"] for e in events]
        assert names[0] == "auth_limiter_degraded"
        assert names[-1] == "auth_limiter_healthy"
        assert names.count("auth_limiter_healthy") == 1
        assert names.count("auth_limiter_recovering") >= 2
        assert names.count("auth_limiter_degraded") >= 2
        assert names.count("auth_limiter_probe_failed") >= 1
        assert events[-1]["duration_seconds"] >= 25
        assert len({e["process_id"] for e in events}) == 1
        serialized = json.dumps(events)
        for secret in (
            auth_user["email"],
            auth_user["password"],
            "absent@example.test",
            "127.0.0.1",
            "ros_refresh",
            "ros_access",
        ):
            assert secret not in serialized
