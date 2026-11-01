import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def benchmark(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "monitoring_benchmark", ROOT / "scripts/benchmark-monitoring.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1MiB", 1048576), ("1 MB", 1000000), ("1.5GiB", 1610612736), ("128B", 128)],
)
def test_docker_memory_units_preserve_binary_decimal_distinction(
    benchmark, raw, expected
):
    assert benchmark.memory_bytes(raw) == expected


def test_unknown_resource_measurement_is_not_a_healthy_zero(benchmark):
    with pytest.raises(ValueError):
        benchmark.memory_bytes("--")


def test_resource_identity_accepts_unique_short_ids_and_rejects_ambiguity(benchmark):
    first = "a" * 64
    second = "a" * 12 + "b" * 52
    assert benchmark.service_for_id({first: "collector"}, first[:12]) == "collector"
    with pytest.raises(ValueError, match="ambiguous"):
        benchmark.service_for_id({first: "collector", second: "grafana"}, first[:12])


def test_docker_render_controls_are_not_resource_samples(benchmark):
    assert benchmark.stats_record('\x1b[H{"CPUPerc":"0.01%"}\x1b[K\n') == {
        "CPUPerc": "0.01%"
    }
    assert benchmark.stats_record("\x1b[K\n") is None
    with pytest.raises(ValueError):
        benchmark.stats_record("invalid resource observation")
