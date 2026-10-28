"""The rehearsal helper must never target the developer database or project."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def helper(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "local_gateway", ROOT / "scripts/local-gateway.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = tmp_path / ".local-gateway"
    state.mkdir()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "STATE", state)
    (state / "state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "project": "restaurantos-gateway-0123456789ab",
                "port": 8443,
                "subnet": "10.249.42.0/24",
                "proxy_ip": "10.249.42.2",
            }
        )
    )
    (state / "backend.env").write_text(
        "DATABASE_URL=postgresql+asyncpg://gateway@postgres:5432/restaurantos_gateway_test\n"
    )
    return module


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://gateway@localhost:5433/restaurantos",
        "postgresql+asyncpg://gateway@postgres:5432/restaurantos",
        "postgresql+asyncpg://gateway@external.test:5432/restaurantos_gateway_test",
    ],
)
def test_rehearsal_rejects_foreign_database(helper, url):
    (helper.STATE / "backend.env").write_text("DATABASE_URL=" + url)
    with pytest.raises(RuntimeError, match="outside the isolated"):
        helper.load()


def test_rehearsal_rejects_foreign_project(helper):
    path = helper.STATE / "state.json"
    state = json.loads(path.read_text())
    state["project"] = "restaurantos"
    path.write_text(json.dumps(state))
    with pytest.raises(RuntimeError, match="project marker"):
        helper.load()


def test_operation_lock_survives_nested_attempt_and_cleans_on_failure(helper):
    with pytest.raises(ValueError, match="injected"):
        with helper.exclusive_operation():
            with pytest.raises(RuntimeError, match="active or interrupted"):
                with helper.exclusive_operation():
                    pytest.fail("Concurrent mutation must not execute")
            assert (helper.STATE / "operation.lock").exists()
            raise ValueError("injected")
    assert not (helper.STATE / "operation.lock").exists()


@pytest.mark.parametrize(
    "state",
    [
        {"Running": True},
        {"Running": False, "Paused": True},
        {"Running": False, "Restarting": True},
    ],
)
def test_migration_rejects_live_writers(helper, monkeypatch, state):
    calls = []

    def compose(*args, **kwargs):
        calls.append(args)
        return "owned-api-container"

    monkeypatch.setattr(helper, "compose", compose)
    monkeypatch.setattr(helper, "docker", lambda *_: json.dumps([{"State": state}]))
    with pytest.raises(RuntimeError, match="Stop API and worker"):
        helper.migrate(helper.load())
    assert not any("run" in call for call in calls)


def test_schema_mismatch_never_starts_application_writers(helper, monkeypatch):
    calls = []

    def compose(state, *args, **kwargs):
        calls.append(args)
        if args[0] == "exec":
            return "old-revision"
        if args[0] == "run":
            return "new-revision (head)"
        return ""

    monkeypatch.setattr(helper, "compose", compose)
    state = helper.load()
    state.update(
        backend_image="sha256:" + "a" * 64, frontend_image="sha256:" + "b" * 64
    )
    with pytest.raises(RuntimeError, match="schema does not match"):
        helper.start(state)
    assert not any("--wait-timeout" in call for call in calls)


def test_compose_never_pulls_a_fallback_application_image(helper):
    with pytest.raises(RuntimeError, match="record both application image IDs"):
        helper.compose(helper.load(), "up", "-d")


@pytest.mark.parametrize(
    "endpoint",
    ["ssh://operator@remote.test", "tcp://remote.test:2376", "tcp://127.0.0.1:2375"],
)
def test_remote_engine_is_rejected_before_mutation(helper, monkeypatch, endpoint):
    monkeypatch.setenv("DOCKER_HOST", endpoint)
    monkeypatch.setattr(
        helper, "docker", lambda *_: pytest.fail("Remote engine must not be contacted")
    )
    with pytest.raises(RuntimeError, match="local Docker socket"):
        helper.require_local_engine()
