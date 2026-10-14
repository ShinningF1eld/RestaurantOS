"""Pure retry, classification and safe operator-output contracts."""

import json
import logging

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.logging import JsonFormatter
from app.modules.events.domain.diagnostics import safe_category, safe_identifier
from app.modules.events.domain.retries import RetryPolicy
from app.modules.events.execution import DependencyUnavailable, classify_failure


REDACTION_URL = "redis://user:secret@host"  # pragma: allowlist secret


def test_retry_budget_and_bounded_jitter():
    policy = RetryPolicy()
    assert policy.max_attempts == 8
    assert [policy.delay_seconds(n, 0) for n in range(1, 8)] == [1, 2, 4, 8, 16, 32, 60]
    for n in range(1, 100):
        base = policy.delay_seconds(n, 0)
        assert base <= policy.delay_seconds(n, 1) <= min(60, base * 1.1)
    with pytest.raises(ValueError):
        policy.delay_seconds(1, 1.1)
    with pytest.raises(ValueError):
        RetryPolicy(0)


@pytest.mark.parametrize(
    "code,infrastructure",
    [
        ("08006", True),
        ("28P01", True),
        ("53300", True),
        ("57P01", True),
        ("40001", False),
        ("40P01", False),
        ("23505", False),
    ],
)
def test_sqlstate_classification_does_not_use_driver_text(code, infrastructure):
    class DriverError(Exception):
        sqlstate = code

    failure = classify_failure(
        OperationalError("sensitive sql", {}, DriverError("password=secret"))
    )
    assert failure.infrastructure is infrastructure
    assert classify_failure(DriverError("secret")).infrastructure is infrastructure
    assert "secret" not in failure.category
    if code.startswith("23"):
        assert failure.permanent
        assert classify_failure(DriverError("secret")).permanent


def test_constraint_and_shared_dependency_categories():
    assert classify_failure(IntegrityError("", {}, Exception("secret"))).permanent
    assert classify_failure(DependencyUnavailable("secret")).infrastructure
    assert not classify_failure(RuntimeError("secret")).infrastructure


def test_safe_inspection_and_attempt_log_allowlist():
    assert safe_identifier(REDACTION_URL) == "redacted"
    assert safe_category("customer payload") == "redacted"
    record = logging.LogRecord(
        "events", logging.INFO, "", 0, "event_consumer_attempt", (), None
    )
    record.attempt_id = "attempt-id"
    record.attempt_number = 2
    record.replay_id = "replay-id"
    record.payload = "customer-secret"
    record.redis_url = "redis://secret"
    output = JsonFormatter().format(record)
    assert json.loads(output)["attempt_number"] == 2
    assert "secret" not in output
