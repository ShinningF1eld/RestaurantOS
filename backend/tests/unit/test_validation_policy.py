"""Required gates and failure cleanup must not silently lose worker coverage."""

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def load_runner(monkeypatch, relative):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("validation_policy", ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ci_requires_all_shared_gates_and_unchanged_aggregate(monkeypatch):
    runner = load_runner(monkeypatch, "scripts/validate.py")
    assert runner.GATES == (
        "baseline",
        "backend-static",
        "frontend-static",
        "backend-unit",
        "backend-integration",
        "frontend-tests",
        "frontend-build",
        "migrations",
        "browser",
        "image",
    )
    workflow = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader
    )
    quality = workflow["jobs"]["quality"]
    assert set(quality["strategy"]["matrix"]) == {"gate"}
    assert quality["strategy"]["matrix"]["gate"] == list(runner.GATES)
    assert quality["strategy"]["fail-fast"] == "false"
    assert "if" not in quality
    steps = quality["steps"]
    shared = next(step for step in steps if step.get("name") == "Run shared gate")
    assert (
        shared["run"]
        == "python scripts/validate.py --gate ${{ matrix.gate }} --external-services --no-install"
    )
    assert "if" not in shared and "continue-on-error" not in shared
    assert "continue-on-error" not in quality
    acceptance = workflow["jobs"]["acceptance"]
    assert "continue-on-error" not in acceptance
    assert acceptance["name"] == "Milestone 6 acceptance"
    assert acceptance["needs"] == "quality" and acceptance["if"] == "always()"
    aggregate = acceptance["steps"][0]
    assert "if" not in aggregate and "continue-on-error" not in aggregate
    assert aggregate["env"]["QUALITY_RESULT"] == "${{ needs.quality.result }}"
    assert aggregate["run"] == 'test "$QUALITY_RESULT" = success'
    assert workflow["on"] == {"push": "", "pull_request": "", "merge_group": ""}


def test_integration_gate_includes_all_worker_suites_and_drift(monkeypatch):
    from contextlib import nullcontext

    runner = load_runner(monkeypatch, "scripts/validate.py")
    import test_support.disposable_postgres as postgres

    database = Mock()
    database.environment.return_value = {"isolated": "yes"}
    monkeypatch.setattr(
        postgres, "disposable_database", lambda **_: nullcontext(database)
    )
    calls = []
    monkeypatch.setattr(runner, "run", lambda *args, **kwargs: calls.append(args))
    tests = Mock()
    monkeypatch.setattr(runner, "backend_tests", tests)
    runner.gate("backend-integration", {"TEST_DATABASE_URL": "guarded-template"})
    tests.assert_called_once_with(
        "backend-integration", ["tests", "--ignore=tests/unit"], {"isolated": "yes"}
    )
    assert [call[3:] for call in calls] == [("upgrade", "head"), ("check",)]


def test_failed_compose_start_still_removes_only_its_own_project(monkeypatch):
    runner = load_runner(monkeypatch, "scripts/validate.py")
    calls = []

    def run(*args):
        calls.append(args)
        if "up" in args:
            raise RuntimeError("injected startup failure")

    monkeypatch.setattr(runner, "run", run)
    with pytest.raises(RuntimeError, match="injected startup failure"):
        with runner.services(False):
            pytest.fail("Unhealthy services must never be yielded")
    assert calls[0][:6] == calls[1][:6]
    assert calls[1][5].startswith("restaurantos-m6-")
    assert calls[1][6:] == ("down", "--volumes", "--remove-orphans")


def test_cleanup_kills_stalled_worker_and_still_waits_for_api(monkeypatch):
    load_runner(monkeypatch, "scripts/validate.py")
    from test_support.processes import stop_processes

    worker, api = Mock(), Mock()
    worker.poll.return_value = api.poll.return_value = None
    worker.wait.side_effect = [subprocess.TimeoutExpired("worker", 10), 0]
    stop_processes(worker, api)
    worker.kill.assert_called_once()
    api.terminate.assert_called_once()
    api.wait.assert_called_once_with(timeout=10)


def test_cleanup_error_does_not_leave_other_owned_process_running(monkeypatch):
    load_runner(monkeypatch, "scripts/validate.py")
    from test_support.processes import stop_processes

    worker, api = Mock(), Mock()
    worker.poll.side_effect = OSError("injected cleanup failure")
    api.poll.return_value = None
    with pytest.raises(ExceptionGroup):
        stop_processes(worker, api)
    api.terminate.assert_called_once()
    api.wait.assert_called_once_with(timeout=10)


def test_unit_gate_removes_worker_and_service_configuration(monkeypatch):
    runner = load_runner(monkeypatch, "scripts/validate.py")
    for key in (
        "EVENT_WORKER_MAX_ATTEMPTS",
        "TEST_DATABASE_URL",
        "REDIS_URL",
        "AUTH_JWT_SECRET",
    ):
        monkeypatch.setenv(key, "ambient")
    tests = Mock()
    monkeypatch.setattr(runner, "backend_tests", tests)
    runner.gate("backend-unit", {})
    label, selectors, env = tests.call_args.args
    assert label == "backend-unit" and selectors == ["tests/unit"]
    assert not any(
        key.startswith(("EVENT_WORKER_", "TEST_DATABASE", "REDIS", "AUTH_"))
        for key in env
    )


@pytest.mark.parametrize(
    "fault", [None, "startup", "wrong_test", "leak", "cleanup_error"]
)
def test_browser_cleanup_probe_requires_intended_failure_and_no_leaks(
    monkeypatch, tmp_path, fault
):
    runner = load_runner(monkeypatch, "scripts/validate.py")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    report = tmp_path / "test-results/browser-cleanup/results.xml"
    report.parent.mkdir(parents=True)
    # A stale expected report must not turn a startup failure into a pass.
    report.write_text(
        '<testsuite><testcase name="diagnostic failure"><failure /></testcase></testsuite>'
    )
    report.with_name("cleanup-complete.json").write_text('{"cleanup_completed": true}')
    results = iter(
        ["existing\n", "existing\nleaked\n" if fault == "leak" else "existing\n"]
    )
    monkeypatch.setattr(
        runner.subprocess, "check_output", lambda *a, **k: next(results)
    )

    def launch(*args, **kwargs):
        if fault != "startup":
            name = "unrelated test" if fault == "wrong_test" else "diagnostic failure"
            report.write_text(
                f'<testsuite><testcase name="{name}"><failure /></testcase></testsuite>'
            )
            if fault != "cleanup_error":
                report.with_name("cleanup-complete.json").write_text(
                    '{"cleanup_completed": true}'
                )
        return subprocess.CompletedProcess(args[0], 1)

    monkeypatch.setattr(runner.subprocess, "run", launch)
    if fault:
        with pytest.raises(RuntimeError):
            runner.browser_cleanup_probe({})
    else:
        runner.browser_cleanup_probe({})


def test_browser_gate_requires_workflow_and_cleanup_probe(monkeypatch):
    runner = load_runner(monkeypatch, "scripts/validate.py")
    run, probe, gateway_probe = Mock(), Mock(), Mock()
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(runner, "browser_cleanup_probe", probe)
    monkeypatch.setattr(runner, "gateway_cleanup_probe", gateway_probe)
    env = {"isolated": "yes"}
    runner.gate("browser", env)
    assert [call.args[1] for call in run.call_args_list] == [
        "scripts/run-browser-tests.py",
        "scripts/run-gateway-browser-tests.py",
    ]
    probe.assert_called_once_with(env)
    gateway_probe.assert_called_once_with(env)


@pytest.mark.parametrize(
    "failed_script", [None, "check-backend-image.py", "check-frontend-image.py"]
)
def test_image_gate_requires_both_images_and_propagates_failure(
    monkeypatch, failed_script
):
    runner = load_runner(monkeypatch, "scripts/validate.py")
    calls = []

    def run(*args, **kwargs):
        calls.append(args[1])
        if failed_script and args[1].endswith(failed_script):
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(runner, "run", run)
    if failed_script:
        with pytest.raises(subprocess.CalledProcessError):
            runner.gate("image", {})
    else:
        runner.gate("image", {})
    assert calls[0] == "scripts/check-backend-image.py"
    if failed_script != "check-backend-image.py":
        assert calls == [
            "scripts/check-backend-image.py",
            "scripts/check-frontend-image.py",
        ]


@pytest.mark.parametrize("leaked", [False, True])
def test_frontend_smoke_failure_cleans_only_owned_container(monkeypatch, leaked):
    runner = load_runner(monkeypatch, "scripts/check-frontend-image.py")
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        output = ""
        if args[0] == "port":
            output = "127.0.0.1:32100"
        elif args[0] == "ps" and leaked:
            output = "leaked-container"
        return subprocess.CompletedProcess(args, 0, stdout=output)

    monkeypatch.setattr(runner, "docker", docker)
    monkeypatch.setattr(runner, "fetch", lambda *_: b"unexpected homepage")
    expected = "cleanup failed" if leaked else "homepage did not render"
    with pytest.raises(RuntimeError, match=expected):
        runner.smoke("test-image", 1, False)
    name = calls[0][calls[0].index("--name") + 1]
    assert name.startswith("restaurantos-frontend-image-")
    assert ("rm", "--force", name) in calls
    assert calls[-1] == ("ps", "-aq", "--filter", f"name=^/{name}$")
