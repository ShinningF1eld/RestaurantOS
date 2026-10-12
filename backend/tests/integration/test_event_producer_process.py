"""Physical API death after commit leaves PostgreSQL work discoverable."""

import json
import os
import queue
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import text

from conftest import engine
from integration.test_event_producers import tracked_order, events, assert_fanout


def test_api_death_after_commit_leaves_complete_recoverable_fanout(
    authenticated_client,
    auth_user,
    tmp_path,
):
    _, _, _, order = tracked_order(authenticated_client)
    baseline = {e["event_id"] for e in events()}
    backend = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "PYTHONPATH": str(backend),
        "REDIS_URL": "redis://127.0.0.1:1/0",
        "REDIS_TEST_NAMESPACE": "event-crash-" + uuid4().hex,
    }
    # A real API with unavailable Redis uses the existing local auth fallback.
    with (tmp_path / "api.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(backend / "tests/support/event_commit_process.py")],
            cwd=backend,
            env=env,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )
        messages = queue.Queue()

        def read():
            for line in process.stdout:
                messages.put(json.loads(line))
            messages.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            ready = messages.get(timeout=25)
            assert ready is not None
            with httpx.Client(
                base_url=f"http://127.0.0.1:{ready['port']}",
                headers={
                    "Origin": "http://localhost:3000",
                    "X-CSRF-Protection": "1",
                    "X-Request-ID": "crash-accept",
                },
                timeout=25,
            ) as client:
                assert (
                    client.post(
                        "/auth/login",
                        json={
                            "email": auth_user["email"],
                            "password": auth_user["password"],
                        },
                    ).status_code
                    == 200
                )
                with ThreadPoolExecutor(max_workers=1) as executor:
                    request = executor.submit(
                        client.put, f"/api/orders/{order}", json={"status": "ACCEPTED"}
                    )
                    boundary = messages.get(timeout=25)
                    assert boundary == {"committed": order}
                    process.kill()
                    process.wait(timeout=10)
                    try:
                        request.result(timeout=10)
                    except httpx.TransportError:
                        pass
                    else:
                        raise AssertionError(
                            "Killed API must not complete the response"
                        )
            # Fresh independent database connection after the API has died:
            # later worker's durable recovery source, with no Redis publication.
            with engine.connect() as db:
                assert (
                    db.scalar(
                        text("SELECT status FROM orders WHERE order_id=:o"),
                        {"o": order},
                    )
                    == "ACCEPTED"
                )
                assert (
                    db.scalar(
                        text(
                            "SELECT count(*) FROM inventory_movements WHERE order_id=:o"
                        ),
                        {"o": order},
                    )
                    == 1
                )
                recoverable = (
                    db.execute(
                        text(
                            "SELECT e.event_type,e.correlation_id,d.consumer_name,d.status,d.attempt_count,d.published_at FROM outbox_events e JOIN event_deliveries d USING (event_id) WHERE e.correlation_id='crash-accept'"
                        )
                    )
                    .mappings()
                    .all()
                )
            assert len(recoverable) == 4
            assert {r["event_type"] for r in recoverable} == {
                "order.accepted.v1",
                "inventory.state_changed.v1",
                "inventory.low.v1",
            }
            assert all(
                r["status"] == "pending"
                and r["attempt_count"] == 0
                and r["published_at"] is None
                for r in recoverable
            )
            assert len([e for e in events() if e["event_id"] not in baseline]) == 3
            assert_fanout()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            reader.join(timeout=2)
            process.stdout.close()
