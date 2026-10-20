"""Freshness measurements must bound commits and expose missing observations."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def benchmark():
    path = Path(__file__).resolve().parents[3] / "scripts/benchmark-event-freshness.py"
    spec = importlib.util.spec_from_file_location("event_freshness_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_latency_bounds_include_both_commit_and_poll_uncertainty(benchmark):
    bounds = benchmark.latency_bounds(10, 10.010, 15.020, 15.050)
    assert bounds["upper_ms"] == pytest.approx(5050)
    assert bounds["lower_ms"] == pytest.approx(5010)
    assert bounds["commit_bracket_ms"] == pytest.approx(10)
    assert bounds["observation_bracket_ms"] == pytest.approx(30)


def test_receipt_visible_before_producer_ack_has_zero_lower_bound(benchmark):
    # Consumer may commit before the producer client receives its COMMIT reply.
    bounds = benchmark.latency_bounds(10, 10.020, 9.99, 10.015)
    assert bounds["lower_ms"] == 0
    assert bounds["upper_ms"] == pytest.approx(15)


def test_empty_measurement_does_not_claim_zero_latency(benchmark):
    result = benchmark.distribution([])
    assert result["count"] == 0
    assert result["p95_ms"] is None and result["max_ms"] is None


def test_nearest_rank_and_strict_five_second_misses(benchmark):
    result = benchmark.distribution([5001, 1, 5000, 3, 2])
    assert result["p50_ms"] == 3
    assert result["p95_ms"] == result["p99_ms"] == 5001
    assert result["over_5000_ms"] == 1
