import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

load_dotenv()
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set; tests refuse to truncate DATABASE_URL"
    )

database_name = make_url(TEST_DATABASE_URL).database or ""
if not database_name.endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL database name must end with '_test'")

# Application modules are imported only after pytest loads this conftest. Point
# the application at the same isolated database used by the cleanup fixture.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"

sync_url = TEST_DATABASE_URL.replace(
    "postgresql+asyncpg://", "postgresql+psycopg://"
)
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
