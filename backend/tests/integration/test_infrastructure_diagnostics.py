"""Real independently pooled API/worker processes; HTTP tests use NullPool."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("role", ["api", "worker"])
def test_real_pool_saturation_timeout_cancellation_and_recovery(role):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("infrastructure_probe.py")),
            role,
        ],
        # Explicit fixture pool sizes bound the test, without changing app defaults.
        env={
            **os.environ,
            "DATABASE_POOL_SIZE": "2",
            "DATABASE_MAX_OVERFLOW": "1",
            "DATABASE_POOL_TIMEOUT_SECONDS": "1",
            "MONITORING_SQL_SLOW_SECONDS": "0.001",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert {
        p["attributes"]["outcome"] for p in data["restaurantos.pool.acquire.failures"]
    } == {"timeout", "cancelled"}
    assert any(
        p["attributes"]["operation"] == "SELECT"
        for p in data["restaurantos.sql.duration"]
    )
    assert any(
        p["attributes"]["outcome"] == "database"
        for p in data["restaurantos.sql.failures"]
    )
    assert any(
        p["attributes"]["outcome"] == "cancelled"
        for p in data["restaurantos.sql.failures"]
    )
    assert sum(p["value"] for p in data["restaurantos.sql.slow"]) > 0
    assert {"SELECT", "INSERT", "UPDATE", "DELETE", "OTHER"} <= {
        p["attributes"]["operation"] for p in data["restaurantos.sql.duration"]
    }
