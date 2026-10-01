"""Provision an ephemeral browser account only in an explicitly isolated test DB."""
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

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
engine = create_engine(url.replace("postgresql+asyncpg://", "postgresql+psycopg://"), connect_args={"connect_timeout": 5}, hide_parameters=True)
with engine.begin() as connection:
    if sys.argv[1] == "delete":
        connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
    elif sys.argv[1] == "create":
        account = json.load(sys.stdin)
        connection.execute(text("INSERT INTO users (id,email,password_hash,status) VALUES (:id,:email,:hash,'active')"), {"id": user_id, "email": account["email"], "hash": asyncio.run(hash_password(account["password"]))})
    else:
        raise ValueError("Unknown fixture operation")
