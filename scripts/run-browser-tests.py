"""Run Chromium using a disposable database, production build and ports."""

import argparse
import os
import re
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from test_support.disposable_postgres import disposable_database
from test_support.redis_environment import redis_environment

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def checked(command, *, cwd, env):
    subprocess.run(command, cwd=cwd, env=env, check=True)


def safe_diagnostics(value, env):
    """Remove generated authentication values from assertion/call logs."""
    for key in (
        "AUTH_JWT_SECRET",
        "AUTH_RATE_LIMIT_SECRET",
        "DATABASE_URL",
        "TEST_DATABASE_URL",
        "REDIS_URL",
    ):
        secret = env.get(key)
        if secret:
            value = value.replace(secret, "[redacted configuration]")
    value = re.sub(r"Browser test [0-9a-f-]{36}", "[redacted test password]", value)
    value = re.sub(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        "[redacted JWT]",
        value,
    )
    return re.sub(
        r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])",
        "[redacted opaque token]",
        value,
    )


def browser_tests(command, *, cwd, env, artifacts):
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        print(safe_diagnostics(result.stdout, env), end="")
        print(safe_diagnostics(result.stderr, env), end="", file=sys.stderr)
        result.check_returncode()
    finally:
        for path in artifacts.rglob("*"):
            if path.is_file() and path.suffix in {".xml", ".md", ".txt", ".json"}:
                value = path.read_text(encoding="utf-8")
                path.write_text(safe_diagnostics(value, env), encoding="utf-8")


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextmanager
def frontend_copy():
    folder = Path(tempfile.mkdtemp(prefix=".m6-browser-", dir=ROOT)).resolve()
    frontend = folder / "frontend"
    junction = frontend / "node_modules"
    try:
        shutil.copytree(
            ROOT / "frontend",
            frontend,
            ignore=shutil.ignore_patterns(
                "node_modules",
                ".next",
                "coverage",
                "test-results",
                "playwright-report",
                ".env",
                ".env.*",
                "*.tsbuildinfo",
            ),
        )
        dependencies = ROOT / "frontend" / "node_modules"
        if not dependencies.is_dir():
            raise RuntimeError("Install frontend dependencies with npm ci first")
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(dependencies)],
                check=True,
                capture_output=True,
            )
        else:
            junction.symlink_to(dependencies, target_is_directory=True)
        config = frontend / "next.config.ts"
        config.rename(frontend / "next.config.base.ts")
        config.write_text(
            'import config from "./next.config.base";\n'
            "export default { ...config, turbopack: { ...config.turbopack, "
            "root: process.env.M6_SOURCE_ROOT } };\n",
            encoding="utf-8",
        )
        yield frontend
    finally:
        if junction.exists():
            if os.name == "nt":
                os.rmdir(junction)
            else:
                junction.unlink()
        if folder.parent != ROOT.resolve() or not folder.name.startswith(
            ".m6-browser-"
        ):
            raise RuntimeError("Refusing cleanup outside the browser workspace")
        shutil.rmtree(folder)


def main():
    # Node diagnostics use UTF-8, including Playwright's failure separators.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grep", help="Partial run; does not count as full verification"
    )
    parser.add_argument(
        "--inject-failure", action="store_true", help="Verify diagnostics and cleanup"
    )
    args = parser.parse_args()
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm is required")
    api_port, web_port = free_port(), free_port()
    while web_port == api_port:
        web_port = free_port()
    origin, api = f"http://localhost:{web_port}", f"http://localhost:{api_port}"
    artifacts = ROOT / "test-results" / "browser"
    artifacts.mkdir(parents=True, exist_ok=True)
    owned_redis = runpy.run_path(str(BACKEND / "tests/support/owned_redis.py"))[
        "owned_redis"
    ]
    with (
        disposable_database(prefix="restaurantos_browser") as database,
        owned_redis() as (redis_container, redis_port),
    ):
        env = redis_environment(
            {
                **database.environment(),
                "TEST_REDIS_HOST": "127.0.0.1",
                "TEST_REDIS_PORT": redis_port,
            }
        )
        env.update(
            {
                "NEXT_PUBLIC_API_URL": api,
                "API_URL": api,
                "AUTH_COOKIE_SECURE": "false",
                "AUTH_TRUSTED_ORIGINS": f'["{origin}"]',
                "AUTH_LOGIN_EMAIL_LIMIT": "5",
                "AUTH_LOGIN_IP_LIMIT": "30",
                "AUTH_LOGIN_WINDOW_SECONDS": "60",
                "AUTH_LOGIN_IP_WINDOW_SECONDS": "900",
                "AUTH_REFRESH_FAMILY_LIMIT": "10",
                "AUTH_REFRESH_IP_LIMIT": "100",
                "AUTH_REFRESH_WINDOW_SECONDS": "60",
                "AUTH_LOCAL_MAX_ENTRIES": "10000",
                "PLAYWRIGHT_REDIS_CONTAINER": redis_container,
                "PLAYWRIGHT_BASE_URL": origin,
                "PLAYWRIGHT_WEB_PORT": str(web_port),
                "PLAYWRIGHT_PYTHON": sys.executable,
                "PYTHONPATH": str(BACKEND),
                "M6_SOURCE_ROOT": str(ROOT),
                "PLAYWRIGHT_ARTIFACTS": str(artifacts),
            }
        )
        for key in (
            "PLAYWRIGHT_EXTERNAL_SERVER",
            "AUTH_ACCESS_SECONDS",
            "AUTH_SESSION_SECONDS",
        ):
            env.pop(key, None)
        checked(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env
        )
        with frontend_copy() as frontend:
            checked([npm, "run", "build"], cwd=frontend, env=env)
            if args.inject_failure:
                (frontend / "tests" / "diagnostic-failure.spec.ts").write_text(
                    'import { test, expect } from "@playwright/test";\n'
                    'test("diagnostic failure", async ({ page }) => { '
                    'await page.goto("/login"); expect(true).toBe(false); });\n',
                    encoding="utf-8",
                )
            env["PLAYWRIGHT_API_LOG"] = str(frontend.parent / "browser-api.log")
            with open(env["PLAYWRIGHT_API_LOG"], "w+", encoding="utf-8") as log:
                server = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(api_port),
                        "--no-proxy-headers",
                    ],
                    cwd=frontend.parent,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                try:
                    for _ in range(150):
                        if server.poll() is not None:
                            raise RuntimeError(
                                "Isolated test API exited before startup"
                            )
                        try:
                            with urlopen(f"{api}/health", timeout=1) as response:
                                if response.status == 200:
                                    break
                        except (URLError, TimeoutError):
                            time.sleep(0.2)
                    else:
                        raise RuntimeError("Isolated test API did not become healthy")
                    command = [npm, "run", "test:e2e", "--"]
                    if args.inject_failure:
                        command.append("diagnostic-failure.spec.ts")
                    elif args.grep:
                        command.extend(["--grep", args.grep])
                    browser_tests(command, cwd=frontend, env=env, artifacts=artifacts)
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()
    print("PASS: isolated Chromium suite and cleanup")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(f"FAIL: browser subprocess returned {error.returncode}", file=sys.stderr)
        raise SystemExit(error.returncode) from None
