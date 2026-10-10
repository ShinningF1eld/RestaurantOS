"""Comparison evidence rejects workload drift and invalid hit/query accounting."""

import copy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def report():
    source = (
        Path(__file__).resolve().parents[3] / "scripts/report-menu-read-comparison.py"
    )
    spec = importlib.util.spec_from_file_location("menu_report", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measurements():
    metadata = {
        "benchmark_configuration": {
            "measured_requests_per_scenario_level_repetition": 1000,
            "warmup_requests_per_scenario_level_repetition": 50,
            "percentile_method": "nearest-rank",
            "repetitions": 3,
        },
        "dataset": {"menus": 4, "menu_items": 160},
        "workloads": {"mixed-write": "80% reads/20% writes"},
    }
    rows = [
        {
            "scenario": "mixed-write",
            "concurrency": 10,
            "repetition": index,
            "request_count": 1000,
            "successful_request_count": 1000,
            "error_count": 0,
            "queries_per_request": 6,
            "sql_phase_costs": {"authorization": {"queries_per_request": 6}},
            "cache_lookup_count": 800,
            "cache_hit_count": 700,
        }
        for index in (1, 2, 3)
    ]
    baseline = {"cache_mode": "disabled", "metadata": metadata, "results": rows}
    candidate = copy.deepcopy(baseline)
    candidate["cache_mode"] = "warm"
    return baseline, candidate


@pytest.mark.parametrize(
    "drift",
    [
        "requests",
        "seed",
        "mix",
        "missing_cell",
        "duplicate_cell",
        "failure",
        "sql",
        "hits",
        "superseded",
    ],
)
def test_comparison_refuses_incompatible_or_invalid_evidence(report, drift):
    baseline, candidate = measurements()
    if drift == "requests":
        candidate["metadata"]["benchmark_configuration"][
            "measured_requests_per_scenario_level_repetition"
        ] = 20
    elif drift == "seed":
        candidate["metadata"]["dataset"]["menus"] = 5
    elif drift == "mix":
        candidate["metadata"]["workloads"]["mixed-write"] = "60% reads/40% writes"
    elif drift == "missing_cell":
        candidate["results"].pop()
    elif drift == "duplicate_cell":
        candidate["results"].append(copy.deepcopy(candidate["results"][0]))
    elif drift == "failure":
        candidate["results"][0]["error_count"] = 1
    elif drift == "sql":
        candidate["results"][0]["queries_per_request"] = 7
    elif drift == "hits":
        candidate["results"][0]["cache_hit_count"] = 900
    else:
        baseline["metadata"]["benchmark_script_version"] = "1.0.0"
    with pytest.raises(ValueError):
        report.validate_comparison(baseline, candidate)


def test_supplemental_outage_can_select_baseline_cells(report):
    baseline, candidate = measurements()
    candidate["cache_mode"] = "outage"
    candidate["results"] = candidate["results"][:1]
    report.validate_comparison(baseline, candidate)


def test_complete_capture_with_disclosed_transport_error_is_comparable(report):
    baseline, candidate = measurements()
    row = candidate["results"][0]
    row.update(
        successful_request_count=999,
        error_count=1,
        sql_observed_response_count=999,
        sql_unknown_request_count=1,
    )
    report.validate_comparison(baseline, candidate)
    row["sql_unknown_request_count"] = 2
    with pytest.raises(ValueError, match="observation coverage"):
        report.validate_comparison(baseline, candidate)
