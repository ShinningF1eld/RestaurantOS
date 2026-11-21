import runpy
from pathlib import Path

import pytest


@pytest.fixture
def evaluate(monkeypatch):
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return runpy.run_path(str(scripts / "benchmark-local-observability.py"))[
        "local_objectives"
    ]


@pytest.fixture
def repetition():
    requests = [
        {
            "phase": "measurement",
            "operation": operation,
            "outcome": "success",
            "milliseconds": limit,
        }
        for operations, limit, count in (
            (("menu_list", "item_list", "inventory_list", "dashboard"), 100, 36),
            (("menu_ssr",), 200, 36),
            (
                (
                    "stock_receipt",
                    "order_create",
                    "order_submitted",
                    "order_accepted",
                    "order_preparing",
                    "order_ready",
                    "order_completed",
                ),
                150,
                18,
            ),
        )
        for operation in operations
        for _ in range(count)
    ]
    requests.extend(
        {
            "phase": "measurement",
            "operation": "order_create_conflict",
            "outcome": "expected_conflict",
            "milliseconds": 10,
        }
        for _ in range(18)
    )
    return {
        "requests": requests,
        "effects": [
            {
                "phase": "measurement",
                "consumer": consumer,
                "receipt_outcome": "processed",
                "commit_to_effect_seconds": seconds,
            }
            for consumer in ("analytics", "alerts", "notification_sink")
            for seconds in [3] * 19 + [5]
        ],
        "summary": {"peak_monitoring_working_set_bytes": 2_000_000_000},
    }


def test_objectives_include_limits_and_exclude_expected_conflicts(evaluate, repetition):
    results = evaluate(repetition)
    assert all(result["passed"] for result in results.values())
    assert results["unexpected_errors"]["attempts"] == 306


def test_objectives_fail_missing_samples_and_individual_excesses(evaluate, repetition):
    repetition["requests"].pop(0)
    for row in repetition["requests"]:
        if row.get("operation") == "menu_ssr":
            row["milliseconds"] = 200.00001
    repetition["effects"][-1]["commit_to_effect_seconds"] = 5.00001
    repetition["summary"]["peak_monitoring_working_set_bytes"] = None
    results = evaluate(repetition)
    assert {key for key, value in results.items() if not value["passed"]} == {
        "menu_list",
        "menu_ssr",
        "notification_sink",
        "monitoring_memory",
    }


def test_error_objective_is_strictly_below_one_percent(evaluate, repetition):
    requests = repetition["requests"]
    requests[:] = requests[:99] + [
        {"phase": "measurement", "outcome": "unexpected", "operation": "menu_list"}
    ]
    assert not evaluate(repetition)["unexpected_errors"]["passed"]
