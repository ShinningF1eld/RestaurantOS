"""Run the real API and Playwright against an isolated, already migrated DB."""
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

from dotenv import load_dotenv
import psycopg
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
load_dotenv(root / "backend" / ".env")
url = os.environ.get("TEST_DATABASE_URL", "")
if not url or not (make_url(url).database or "").endswith("_test"):
    raise SystemExit("Browser tests require TEST_DATABASE_URL ending in _test.")
try:
    with psycopg.connect(url.replace("postgresql+asyncpg://", "postgresql://"), connect_timeout=5) as connection:
        connection.execute("SELECT 1 FROM users LIMIT 1")
except psycopg.Error:
    raise SystemExit("Browser test database is unavailable or not migrated. Start PostgreSQL and run scripts/migrate-test-db.py.") from None
for port in (8000, 3000):
    with socket.socket() as probe:
        if probe.connect_ex(("localhost", port)) == 0:
            raise SystemExit(f"Port {port} is occupied. Stop the local development server before browser tests.")
environment = {
    **os.environ,
    "DATABASE_URL": url,
    "ENVIRONMENT": "test",
    "AUTH_JWT_SECRET": secrets.token_urlsafe(48),
    "AUTH_RATE_LIMIT_SECRET": secrets.token_urlsafe(48),
    "AUTH_COOKIE_SECURE": "false",
    "AUTH_TRUSTED_ORIGINS": '["http://localhost:3000"]',
    "NEXT_PUBLIC_API_URL": "http://localhost:8000",
    "API_URL": "http://localhost:8000",
    "PLAYWRIGHT_PYTHON": sys.executable,
}
# Browser tests must exercise the stock policy, not developer overrides.
for key in ("AUTH_LOGIN_EMAIL_LIMIT", "AUTH_LOGIN_IP_LIMIT", "AUTH_REFRESH_FAMILY_LIMIT", "AUTH_REFRESH_IP_LIMIT", "AUTH_ACCESS_SECONDS", "AUTH_SESSION_SECONDS"):
    environment.pop(key, None)
environment.pop("PLAYWRIGHT_EXTERNAL_SERVER", None)
npm = shutil.which("npm")
if not npm:
    raise SystemExit("npm is required.")
with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-proxy-headers"],
        cwd=root / "backend", env=environment, stdout=log, stderr=log,
    )
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Test API exited before startup.")
            try:
                with urlopen("http://localhost:8000/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError):
                time.sleep(0.2)
        else:
            raise RuntimeError("Test API did not become healthy.")
        subprocess.run([npm, "run", "test:e2e"], cwd=root / "frontend", env=environment, check=True)
    except Exception:
        log.seek(0)
        print(log.read()[-8000:], file=sys.stderr)
        raise
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
