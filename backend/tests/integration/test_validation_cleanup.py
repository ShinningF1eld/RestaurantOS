"""Exercise failure cleanup of owned services, database and a real worker."""

import asyncio
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.modules.events.worker.redis import WorkerRedisTransport

from integration.test_event_worker import (
    start_process,
    wait_for,
    worker_settings,
)
from support.owned_redis import docker

ROOT = Path(__file__).resolve().parents[3]


def test_injected_failure_cleans_worker_database_and_only_owned_compose(
    monkeypatch, tmp_path
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from test_support.disposable_postgres import disposable_database
    from test_support.processes import stop_processes

    spec = importlib.util.spec_from_file_location(
        "cleanup_validation", ROOT / "scripts/validate.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    with pytest.raises(RuntimeError, match="injected after worker startup"):
        with runner.services(False) as env:
            container = env["TEST_POSTGRES_CONTAINER"]
            project = docker(
                "inspect",
                "--format",
                '{{index .Config.Labels "com.docker.compose.project"}}',
                container,
            )
            assert project.startswith("restaurantos-m6-")
            with disposable_database(test_url=env["TEST_DATABASE_URL"]) as database:
                isolated = database.environment(env)
                subprocess.run(
                    [sys.executable, "-m", "alembic", "upgrade", "head"],
                    cwd=ROOT / "backend",
                    env=isolated,
                    check=True,
                )
                for key, value in isolated.items():
                    monkeypatch.setenv(key, value)
                settings = worker_settings(redis_url=SecretStr(isolated["REDIS_URL"]))
                state = start_process(tmp_path, settings, module=True)
                try:
                    # Creating groups proves the real entrypoint reached Redis.
                    async def groups_created():
                        redis = WorkerRedisTransport(settings)
                        await redis.open()
                        try:
                            return await redis.execute("EXISTS", redis.stream_key())
                        finally:
                            await redis.close()

                    wait_for(lambda: asyncio.run(groups_created()))
                    assert state[0].poll() is None
                    raise RuntimeError("injected after worker startup")
                finally:
                    try:
                        stop_processes(state[0])
                    finally:
                        state[3].close()
                        assert state[0].poll() is not None
            # The outer exception intentionally exercises the service finally.
    for resource in ("container", "network", "volume"):
        assert (
            docker(
                resource,
                "ls",
                "-q",
                "--filter",
                f"label=com.docker.compose.project={project}",
            )
            == ""
        )
    # The database lives in the removed test service; the developer service and
    # its volumes were never selected. Database-drop-on-failure is checked by
    # disposable_database itself before Compose teardown.
