"""Migrate only the explicitly configured disposable test database."""
import os
from pathlib import Path
import subprocess
import sys

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

backend = Path(__file__).resolve().parents[1] / "backend"
load_dotenv(backend / ".env")
url = os.environ.get("TEST_DATABASE_URL", "")
if not url or not (make_url(url).database or "").endswith("_test"):
    raise SystemExit("TEST_DATABASE_URL must name an isolated database ending in _test.")
environment = {**os.environ, "DATABASE_URL": url, "ENVIRONMENT": "test"}
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, env=environment, check=True)
