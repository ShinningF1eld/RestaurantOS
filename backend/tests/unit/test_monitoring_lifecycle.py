"""Ownership guard regressions; no Docker, secrets or service dependencies."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from test_support import monitoring_environment as environment  # noqa: E402


def test_initialization_preserves_private_state_and_never_replaces_credentials(
    tmp_path,
):
    path = tmp_path / "state"
    state = environment.Monitoring.initialize(path)
    before = (path / "grafana_admin_password").read_bytes()
    assert len(before) >= 48
    assert state.project.startswith("restaurantos-monitoring-dev-")
    with pytest.raises(ValueError, match="already exists"):
        environment.Monitoring.initialize(path)
    assert (path / "grafana_admin_password").read_bytes() == before


def test_development_volume_removal_is_rejected_before_docker(tmp_path, monkeypatch):
    state = environment.Monitoring.initialize(tmp_path / "state")
    monkeypatch.setattr(
        environment, "command", lambda *a, **k: pytest.fail("Docker called")
    )
    with pytest.raises(ValueError, match="persistent"):
        state.down(remove_volumes=True)
    with pytest.raises(ValueError, match="persistent"):
        state.compose("down", "--volumes")


def test_tampered_test_identity_cannot_select_developer_resources(tmp_path):
    path = tmp_path / "state"
    state = environment.Monitoring.initialize(path)
    data = state.state
    data["ephemeral"] = True
    (path / "state.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="identity"):
        environment.Monitoring(path)


def test_context_cleans_owned_resources_when_startup_or_work_fails(monkeypatch):
    removed = []
    monkeypatch.setattr(
        environment.Monitoring,
        "down",
        lambda self, **kw: removed.append((self.project, kw["remove_volumes"])),
    )
    with pytest.raises(RuntimeError, match="injected"):
        with environment.disposable_monitoring() as state:
            raise RuntimeError("injected")
    assert removed == [(state.project, True)]
    assert state.project.startswith("restaurantos-monitoring-test-")
