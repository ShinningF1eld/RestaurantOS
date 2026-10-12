"""Browser fixture retirement preserves immutable facts in the disposable DB."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from conftest import engine
from integration.test_event_producers import tracked_order, rows
from integration.test_order_inventory import update_order


def delete_browser_fixture(account):
    # The real browser CLI additionally proves ownership through this slug.
    with engine.begin() as db:
        db.execute(
            text("UPDATE organizations SET slug=:slug WHERE id=:org"),
            {"slug": "browser-" + account["id"], "org": account["organization_id"]},
        )
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[3] / "frontend/tests/seed-auth.py"),
            "delete",
            account["id"],
        ],
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_browser_fixture_with_events_retires_account_and_retains_history(
    authenticated_client, auth_user
):
    _, _, _, order = tracked_order(authenticated_client)
    assert update_order(authenticated_client, order, "ACCEPTED").status_code == 200
    tables = (
        "outbox_events",
        "event_deliveries",
        "inventory_low_stock_episodes",
        "inventory_movements",
        "orders",
    )
    before = {table: rows(table) for table in tables}
    delete_browser_fixture(auth_user)
    for table in tables:
        assert rows(table) == before[table], table
    assert rows("users")[0]["status"] == "disabled"
    assert all(row["revoked_at"] is not None for row in rows("auth_sessions"))
    assert authenticated_client.get(f"/api/orders/{order}").status_code == 401
    assert rows("organizations") and rows("restaurants")


def test_browser_fixture_without_events_removes_owned_account(auth_user):
    delete_browser_fixture(auth_user)
    assert rows("users") == []
    assert rows("organizations") == []
    assert rows("memberships") == []
