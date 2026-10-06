import sys
import socket

import pytest

from app.core.config import get_settings


def test_unit_only_invocation_does_not_create_or_import_database_engine(
    unit_isolation_state,
):
    unit_only, engine = unit_isolation_state
    if not unit_only:
        pytest.skip("the unit-only isolation contract is checked by the unit gate")

    assert engine is None
    assert "app.db.database" not in sys.modules


def test_unit_network_guard_blocks_service_connections():
    for port in (5432, 5433, 6379, 55000):
        with pytest.raises(AssertionError, match="must not open network connections"):
            socket.create_connection(("127.0.0.1", port), timeout=0.1)


def test_unit_settings_cannot_fall_back_to_process_environment_or_dotenv(
    unit_isolation_state,
):
    unit_only, _ = unit_isolation_state
    if not unit_only:
        pytest.skip("the unit-only isolation contract is checked by the unit gate")

    with pytest.raises(AssertionError, match="_env_file=None"):
        get_settings()


@pytest.mark.parametrize(
    "url, message",
    [
        (
            "postgresql+asyncpg://localhost/restaurantos",
            "database name must end with '_test'",
        ),
        (
            "sqlite:///restaurantos_test",
            "must use postgresql",
        ),
    ],
)
def test_integration_database_guard_rejects_unsafe_urls(
    url, message, test_database_url_validator
):
    with pytest.raises(RuntimeError, match=message):
        test_database_url_validator(url)
