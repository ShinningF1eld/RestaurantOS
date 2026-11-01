import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_acceleration_changes_schedules_not_retention_periods():
    fixture = yaml.safe_load((ROOT / "monitoring/testing/retention.yaml").read_text())
    assert "retention_period" not in fixture["loki"].get("limits_config", {})
    assert "block_retention" not in fixture["tempo"]["compactor"]["compaction"]
    assert (
        yaml.safe_load((ROOT / "monitoring/loki.yaml").read_text())["limits_config"][
            "retention_period"
        ]
        == "72h"
    )


def test_retention_rejects_developer_state_before_any_docker_operation(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "monitoring_retention", ROOT / "scripts/check-monitoring-retention.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module, "require_local_engine", lambda: pytest.fail("Docker called")
    )
    with pytest.raises(ValueError, match="disposable"):
        module.run(SimpleNamespace(state={"ephemeral": False}, project="developer"), {})
