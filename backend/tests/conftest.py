import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy import create_engine

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

sync_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg://")
engine = create_engine(sync_url)


@pytest.fixture(autouse=True)
def clean_database() -> None:
    """Tests use the PostgreSQL schema prepared by Alembic, not SQLite."""
    def truncate() -> None:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE order_items, orders, menu_items, menus, restaurants RESTART IDENTITY CASCADE"))
    truncate()
    yield
    truncate()
