"""Disposable browser verification must fail closed and clean only its project."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(monkeypatch, path):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("gateway_browser_runner", ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "name", ["", "../browser-0123456789ab", ".local-gateway", "browser-not-an-id"]
)
def test_fixture_never_accepts_persistent_or_arbitrary_state(monkeypatch, name):
    runner = load(monkeypatch, "scripts/run-gateway-browser-tests.py")
    with pytest.raises(RuntimeError, match="freshly owned"):
        runner.helper_for(name)


def test_cleanup_rejects_persistent_rehearsal_before_docker(monkeypatch, tmp_path):
    runner = load(monkeypatch, "scripts/run-gateway-browser-tests.py")
    monkeypatch.setattr(runner, "BASE", tmp_path)
    helper = SimpleNamespace(STATE=tmp_path, compose=Mock(), docker=Mock())
    with pytest.raises(RuntimeError, match="outside the owned"):
        runner.cleanup(helper, {"browser_run": True})
    helper.compose.assert_not_called()


@pytest.mark.parametrize("paused", [True, False])
def test_cleanup_resumes_only_a_suspended_owned_database(monkeypatch, tmp_path, paused):
    runner = load(monkeypatch, "scripts/run-gateway-browser-tests.py")
    monkeypatch.setattr(runner, "BASE", tmp_path)
    directory = tmp_path / "browser-0123456789ab"
    directory.mkdir()
    helper = SimpleNamespace(
        STATE=directory,
        compose=Mock(return_value="owned-database"),
        docker=Mock(side_effect=[str(paused).lower(), "", "", ""]),
    )
    runner.cleanup(
        helper,
        {
            "browser_run": True,
            "project": "owned",
            "backend_image": "a",
            "frontend_image": "b",
        },
    )
    resumed = any(
        call.args[1:] == ("unpause", "postgres")
        for call in helper.compose.call_args_list
    )
    assert resumed is paused
    assert not directory.exists()


@pytest.mark.parametrize("leak", ["containers", "volumes", "networks"])
def test_cleanup_does_not_claim_success_when_resources_remain(
    monkeypatch, tmp_path, leak
):
    runner = load(monkeypatch, "scripts/run-gateway-browser-tests.py")
    monkeypatch.setattr(runner, "BASE", tmp_path)
    directory = tmp_path / "browser-0123456789ab"
    directory.mkdir()
    helper = SimpleNamespace(STATE=directory, compose=Mock())

    def docker(*args):
        return (
            "owned-resource"
            if args[0]
            == {"containers": "ps", "volumes": "volume", "networks": "network"}[leak]
            else ""
        )

    helper.docker = docker
    with pytest.raises(RuntimeError, match="resources remain"):
        runner.cleanup(
            helper,
            {
                "browser_run": True,
                "project": "owned",
                "backend_image": "a",
                "frontend_image": "b",
            },
        )
    assert directory.exists()


@pytest.mark.parametrize(
    "failure", [None, "startup", "cleanup", "wrong-stage", "unexpected-pass"]
)
def test_gateway_failure_probe_requires_browser_stage_and_cleanup(
    monkeypatch, tmp_path, failure
):
    runner = load(monkeypatch, "scripts/validate.py")
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    def launch(*args, **kwargs):
        if failure != "startup":
            folder = tmp_path / "test-results/gateway-browser/browser-0123456789ab"
            folder.mkdir(parents=True)
            (folder / "results.json").write_text(
                json.dumps(
                    {
                        "passed": failure == "unexpected-pass",
                        "cases": [
                            {
                                "name": "setup"
                                if failure == "wrong-stage"
                                else "intentional failure",
                                "status": "failed",
                            }
                        ],
                    }
                )
            )
            if failure != "cleanup":
                (folder / "cleanup.json").write_text('{"owned_resources_removed":true}')
        return subprocess.CompletedProcess(
            args, 0 if failure == "unexpected-pass" else 1
        )

    monkeypatch.setattr(runner.subprocess, "run", launch)
    if failure:
        with pytest.raises((RuntimeError, OSError)):
            runner.gateway_cleanup_probe({})
    else:
        runner.gateway_cleanup_probe({})
