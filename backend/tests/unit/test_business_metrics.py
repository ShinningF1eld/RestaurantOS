"""Operational counters admit only fixed dimensions and fail open."""

from types import SimpleNamespace
from unittest.mock import Mock

from app.core.business_metrics import order_transition, stock_rejection
from app.core.telemetry import lifecycle


def test_observations_are_bounded_and_optional(monkeypatch, caplog):
    monkeypatch.setattr(lifecycle, "runtime", None)
    order_transition("SUBMITTED")
    stock_rejection("inventory_count_stale")

    metrics = SimpleNamespace(transitions=Mock(), rejections=Mock())
    monkeypatch.setattr(lifecycle, "runtime", SimpleNamespace(business_metrics=metrics))
    order_transition("SUBMITTED")
    stock_rejection("inventory_count_stale")
    for status in ("DRAFT", "ACCEPTED", "private-order-id"):
        order_transition(status)
    stock_rejection("private-payload")
    metrics.transitions.add.assert_called_once_with(1, {"transition": "SUBMITTED"})
    metrics.rejections.add.assert_called_once_with(
        1, {"category": "inventory_count_stale"}
    )

    metrics.transitions.add.side_effect = RuntimeError("private-payload")
    metrics.rejections.add.side_effect = RuntimeError("private-payload")
    order_transition("CANCELLED")
    stock_rejection("order_stock_insufficient")
    assert "observation failed" in caplog.text
    assert "private-payload" not in caplog.text
