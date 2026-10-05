"""Provision an ephemeral browser account only in an explicitly isolated test DB."""

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

url = os.environ.get("TEST_DATABASE_URL", "")
if not url or not (make_url(url).database or "").endswith("_test"):
    raise RuntimeError("Browser tests require TEST_DATABASE_URL ending in _test")
os.environ["DATABASE_URL"] = url
os.environ["ENVIRONMENT"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.modules.auth.security import hash_password

user_id = str(UUID(sys.argv[2]))
engine = create_engine(
    url.replace("postgresql+asyncpg://", "postgresql+psycopg://"),
    connect_args={"connect_timeout": 5},
    hide_parameters=True,
)
with engine.begin() as connection:
    if sys.argv[1] == "delete":
        org = connection.scalar(
            text("SELECT organization_id FROM memberships WHERE user_id=:id"),
            {"id": user_id},
        )
        if org:
            assert (
                connection.scalar(
                    text("SELECT slug FROM organizations WHERE id=:org"), {"org": org}
                )
                == "browser-" + user_id
            )
            # Delete only this fixture's private tenant, in restrictive-FK order.
            for statement in [
                "DELETE FROM inventory_movements WHERE ingredient_id IN (SELECT id FROM inventory_ingredients WHERE restaurant_id IN (SELECT id FROM restaurants WHERE organization_id=:org))",
                "DELETE FROM inventory_balances WHERE ingredient_id IN (SELECT id FROM inventory_ingredients WHERE restaurant_id IN (SELECT id FROM restaurants WHERE organization_id=:org))",
                "DELETE FROM inventory_ingredients WHERE restaurant_id IN (SELECT id FROM restaurants WHERE organization_id=:org)",
                "DELETE FROM audit_entries WHERE organization_id=:org",
                "DELETE FROM restaurant_assignments WHERE organization_id=:org",
                "DELETE FROM memberships WHERE organization_id=:org",
                "DELETE FROM order_items WHERE order_id IN (SELECT order_id FROM orders WHERE restaurant_id IN (SELECT id FROM restaurants WHERE organization_id=:org))",
                "DELETE FROM orders WHERE restaurant_id IN (SELECT id FROM restaurants WHERE organization_id=:org)",
                "DELETE FROM menu_items WHERE menu_id IN (SELECT menu_id FROM menus WHERE restaurant_id IN (SELECT id FROM restaurants WHERE organization_id=:org))",
                "DELETE FROM menus WHERE restaurant_id IN (SELECT id FROM restaurants WHERE organization_id=:org)",
                "DELETE FROM restaurants WHERE organization_id=:org",
                "DELETE FROM organizations WHERE id=:org",
            ]:
                connection.execute(text(statement), {"org": org})
        connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
    elif sys.argv[1] == "create":
        account = json.load(sys.stdin)
        connection.execute(
            text(
                "INSERT INTO users (id,email,password_hash,status) VALUES (:id,:email,:hash,'active')"
            ),
            {
                "id": user_id,
                "email": account["email"],
                "hash": asyncio.run(hash_password(account["password"])),
            },
        )
        organization_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO organizations (id,name,slug) VALUES (:org,'Browser workspace',:slug)"
            ),
            {"org": organization_id, "slug": "browser-" + user_id},
        )
        connection.execute(
            text(
                "INSERT INTO memberships (id,user_id,organization_id,role) VALUES (:member,:user,:org,'OWNER')"
            ),
            {"member": str(uuid4()), "user": user_id, "org": organization_id},
        )
    elif sys.argv[1] == "employee":
        restaurant_id = int(sys.argv[3])
        member = connection.execute(
            text("SELECT id,organization_id FROM memberships WHERE user_id=:id"),
            {"id": user_id},
        ).one()
        assert (
            connection.scalar(
                text("SELECT organization_id FROM restaurants WHERE id=:id"),
                {"id": restaurant_id},
            )
            == member.organization_id
        )
        connection.execute(
            text("UPDATE memberships SET role='EMPLOYEE' WHERE user_id=:id"),
            {"id": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO restaurant_assignments (membership_id,organization_id,restaurant_id) VALUES (:member,:org,:restaurant)"
            ),
            {
                "member": member.id,
                "org": member.organization_id,
                "restaurant": restaurant_id,
            },
        )
    else:
        raise ValueError("Unknown fixture operation")
