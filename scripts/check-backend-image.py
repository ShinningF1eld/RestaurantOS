"""Build, inspect, and smoke-test the production backend image without publishing it."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

import psycopg
from sqlalchemy.engine import URL, make_url
from test_support.disposable_postgres import (
    TestDatabase,
    disposable_database,
    read_test_url,
)

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_IMAGE = "restaurantos-backend:m6"
CONTAINER_PORT = 8000
HEALTH_PATH = "/health"
CONTAINER_DATABASE_CHECK = """\
import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()

asyncio.run(main())
"""
IMAGE_CONTENT_CHECK = """\
from pathlib import Path

root = Path("/app")
required = (root / "app", root / "alembic", root / "alembic.ini")
missing = [str(path) for path in required if not path.exists()]
forbidden_paths = (
    root / ".env",
    root / "requirements.txt",
    root / "requirements.in",
    root / "requirements-dev.txt",
    root / "requirements-dev.in",
    root / "tests",
    root / ".venv",
    root / ".pytest_cache",
    root / ".mypy_cache",
    root / ".ruff_cache",
)
present = [str(path) for path in forbidden_paths if path.exists()]
unexpected = []
for path in root.rglob("*"):
    if path.is_dir() and path.name in {"tests", "__pycache__", ".venv"}:
        unexpected.append(str(path))
    if path.is_file() and (
        path.name.startswith(".env")
        or path.suffix in {".pyc", ".pyo", ".sqlite", ".sqlite3", ".db"}
    ):
        unexpected.append(str(path))
if missing or present or unexpected:
    raise SystemExit("image contents check failed: " + repr({"missing": missing, "present": present, "unexpected": unexpected}))
print("image contents ok")
"""


class ImageCheckError(RuntimeError):
    """A safe-to-report failure from the image verification workflow."""


def run_docker(
    arguments: Sequence[str],
    *,
    description: str,
    redact_values: Sequence[str] = (),
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 and check:
        detail = redact(result.stderr or result.stdout, redact_values)
        if detail:
            print(f"{description} failed:\n{detail[-6000:]}", file=sys.stderr)
        raise ImageCheckError(f"Docker {description} failed (exit {result.returncode})")
    return result


def redact(value: str, secrets_to_hide: Sequence[str]) -> str:
    result = value
    for secret in secrets_to_hide:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result.strip()


def build_image(image: str) -> None:
    print(f"Building backend image {image}", flush=True)
    result = subprocess.run(
        [
            "docker",
            "build",
            "--pull",
            "--tag",
            image,
            "--file",
            str(BACKEND / "Dockerfile"),
            str(BACKEND),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        diagnostics = result.stderr or result.stdout
        if diagnostics:
            print(diagnostics[-8000:], file=sys.stderr)
        raise ImageCheckError(f"Docker image build failed (exit {result.returncode})")
    print(f"Built backend image {image}", flush=True)


def inspect_image(image: str) -> None:
    runtime_version = run_docker(
        [
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            image,
            "--version",
        ],
        description="Python runtime version inspection",
    ).stdout.strip()
    if not runtime_version.startswith("Python 3.12."):
        raise ImageCheckError(
            "Backend image is not running the supported Python 3.12 baseline"
        )

    configured_user = run_docker(
        ["image", "inspect", "--format", "{{.Config.User}}", image],
        description="image user inspection",
    ).stdout.strip()
    if not configured_user or configured_user.split(":", maxsplit=1)[0] in {
        "0",
        "root",
    }:
        raise ImageCheckError("Backend image does not configure a non-root user")

    configured_health = run_docker(
        ["image", "inspect", "--format", "{{json .Config.Healthcheck}}", image],
        description="image healthcheck inspection",
    ).stdout.strip()
    try:
        healthcheck = json.loads(configured_health)
    except json.JSONDecodeError as exc:
        raise ImageCheckError("Could not inspect image healthcheck") from exc
    if (
        not healthcheck
        or not healthcheck.get("Test")
        or HEALTH_PATH not in str(healthcheck["Test"])
    ):
        raise ImageCheckError("Backend image does not define an HTTP /health check")

    configured_env = run_docker(
        ["image", "inspect", "--format", "{{json .Config.Env}}", image],
        description="image environment inspection",
    ).stdout.strip()
    try:
        environment = json.loads(configured_env)
    except json.JSONDecodeError as exc:
        raise ImageCheckError("Could not inspect image environment") from exc
    baked_keys = {item.partition("=")[0] for item in environment}
    if any(
        any(
            marker in key.upper()
            for marker in ("DATABASE_URL", "REDIS_URL", "SECRET", "PASSWORD", "TOKEN")
        )
        for key in baked_keys
    ):
        raise ImageCheckError(
            "Backend image contains runtime database or signing configuration"
        )

    run_docker(
        [
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            image,
            "-c",
            IMAGE_CONTENT_CHECK,
        ],
        description="image contents inspection",
    )
    run_docker(
        [
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            image,
            "-m",
            "pip",
            "check",
        ],
        description="runtime dependency check",
    )
    print(
        f"PASS: {image} uses {configured_user}, has no baked runtime secrets, and contains only runtime files",
        flush=True,
    )


def public_tables(database: TestDatabase) -> tuple[str, ...]:
    with psycopg.connect(database.sync_url) as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ).fetchall()
    return tuple(row[0] for row in rows)


def production_environment(
    database: TestDatabase, *, postgres_host: str | None = None
) -> dict[str, str]:
    runtime = database.environment(base={})
    runtime.pop("TEST_DATABASE_URL", None)
    runtime_url: URL = make_url(database.async_url).set(
        host=postgres_host or "host.docker.internal",
        **({"port": 5432} if postgres_host else {}),
    )
    runtime.update(
        {
            "DATABASE_URL": runtime_url.render_as_string(hide_password=False),
            "ENVIRONMENT": "production",
            "DATABASE_ECHO": "false",
            # Deliberately unavailable inside the container: liveness/startup
            # must work without Redis and without database migrations.
            "REDIS_URL": "redis://127.0.0.1:1/0",
            "REDIS_OPERATION_BUDGET_MS": "100",
            "AUTH_COOKIE_SECURE": "true",
            "AUTH_TRUSTED_ORIGINS": json.dumps(["https://restaurantos.invalid"]),
        }
    )
    return runtime


def create_container(
    *,
    image: str,
    name: str,
    network: str,
    environment: Mapping[str, str],
    use_host_gateway: bool,
) -> str:
    arguments = [
        "run",
        "--detach",
        "--name",
        name,
        "--network",
        network,
        "--publish",
        f"127.0.0.1::{CONTAINER_PORT}",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=512m",
        "--pids-limit=64",
    ]
    if use_host_gateway:
        arguments.extend(["--add-host", "host.docker.internal:host-gateway"])
    for key, value in sorted(environment.items()):
        arguments.extend(["--env", f"{key}={value}"])
    arguments.append(image)
    result = run_docker(
        arguments,
        description="smoke container start",
        redact_values=sensitive_values(environment),
    )
    container_id = result.stdout.strip()
    if not container_id:
        raise ImageCheckError("Docker did not return a smoke container ID")
    return container_id


def published_port(container: str) -> int:
    value = (
        run_docker(
            ["port", container, f"{CONTAINER_PORT}/tcp"],
            description="published port inspection",
        )
        .stdout.strip()
        .splitlines()
    )
    if not value or ":" not in value[0]:
        raise ImageCheckError("Docker did not publish the API port")
    try:
        port = int(value[0].rsplit(":", maxsplit=1)[1])
    except ValueError as exc:
        raise ImageCheckError("Docker returned an invalid published port") from exc
    if not 1 <= port <= 65535:
        raise ImageCheckError("Docker returned an out-of-range published port")
    return port


def wait_for_health(
    container: str,
    port: int,
    timeout: float,
    redact_values: Sequence[str],
) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}{HEALTH_PATH}"
    last_error = "no response"
    while time.monotonic() < deadline:
        status = run_docker(
            ["inspect", "--format", "{{.State.Status}}", container],
            description="container state inspection",
        ).stdout.strip()
        if status in {"exited", "dead", "removing"}:
            logs = run_docker(
                ["logs", container],
                description="container log inspection",
                redact_values=redact_values,
                check=False,
            )
            raise ImageCheckError(
                "Smoke container stopped before /health responded: "
                + redact(logs.stdout + logs.stderr, redact_values)[-4000:]
            )
        try:
            with urlopen(url, timeout=2) as response:
                payload = json.loads(response.read())
                if response.status != 200 or payload != {
                    "status": "ok",
                    "service": "restaurantos-api",
                }:
                    raise ImageCheckError(
                        "Backend /health returned an unexpected response"
                    )
                print(f"PASS: production container is healthy at {url}", flush=True)
                return
        except (OSError, TimeoutError, URLError, json.JSONDecodeError) as exc:
            last_error = type(exc).__name__
            time.sleep(0.5)
    raise ImageCheckError(
        f"Backend /health was not ready within {timeout:.0f}s ({last_error})"
    )


def verify_container_database_connection(
    container: str, environment: Mapping[str, str]
) -> None:
    secret_values = tuple(environment.values())
    result = run_docker(
        ["exec", container, "python", "-c", CONTAINER_DATABASE_CHECK],
        description="isolated database connectivity check",
        redact_values=secret_values,
        check=False,
    )
    if result.returncode != 0:
        message = redact(result.stderr or result.stdout, secret_values)
        raise ImageCheckError(
            "Production container could not connect to its disposable PostgreSQL database"
            + (f": {message[-3000:]}" if message else "")
        )
    print(
        "PASS: production database URL connects to the disposable PostgreSQL database",
        flush=True,
    )


def remove_resources(
    container_name: str | None,
    network_name: str | None,
    postgres_container: str | None = None,
) -> None:
    if container_name:
        existing_container = run_docker(
            ["ps", "-aq", "--filter", f"name=^/{container_name}$"],
            description="smoke container lookup",
        ).stdout.strip()
    else:
        existing_container = ""
    if existing_container:
        run_docker(
            ["rm", "--force", existing_container],
            description="smoke container cleanup",
        )

    if network_name:
        existing_network = run_docker(
            ["network", "ls", "-q", "--filter", f"name=^{network_name}$"],
            description="smoke network lookup",
        ).stdout.strip()
        if existing_network:
            if postgres_container:
                run_docker(
                    [
                        "network",
                        "disconnect",
                        "--force",
                        existing_network,
                        postgres_container,
                    ],
                    description="PostgreSQL smoke network detach",
                    check=False,
                )
            run_docker(
                ["network", "rm", existing_network],
                description="smoke network cleanup",
            )

    if container_name:
        remaining = run_docker(
            ["ps", "-aq", "--filter", f"name=^/{container_name}$"],
            description="smoke container cleanup verification",
        ).stdout.strip()
        if remaining:
            raise ImageCheckError("Smoke container cleanup did not complete")

    if network_name:
        remaining_network = run_docker(
            ["network", "ls", "-q", "--filter", f"name=^{network_name}$"],
            description="smoke network cleanup verification",
        ).stdout.strip()
        if remaining_network:
            raise ImageCheckError("Smoke network cleanup did not complete")


def sensitive_values(environment: Mapping[str, str]) -> tuple[str, ...]:
    values = list(environment.values())
    database_url = environment.get("DATABASE_URL")
    if database_url:
        parsed = make_url(database_url)
        values.extend(value for value in (parsed.username, parsed.password) if value)
    return tuple(values)


def inject_failure(
    stage: str, requested: str | None, container: str, network: str, database: str
) -> None:
    if requested == stage:
        raise ImageCheckError(
            f"Injected failure after {stage}; container={container}; network={network}; database={database}"
        )


def validate_postgres_container(container: str) -> str:
    details = run_docker(
        [
            "inspect",
            "--format",
            '{{.Id}}|{{.State.Running}}|{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "com.docker.compose.project"}}',
            container,
        ],
        description="PostgreSQL service inspection",
    ).stdout.strip()
    try:
        container_id, running, service, project = details.split("|", maxsplit=3)
    except ValueError as exc:
        raise ImageCheckError("PostgreSQL container details were incomplete") from exc
    if (
        running != "true"
        or service != "postgres"
        or not project.startswith("restaurantos-m6-")
    ):
        raise ImageCheckError(
            "--postgres-container must identify a running postgres service in a restaurantos-m6-* Compose project"
        )
    return container_id


def run_smoke(
    image: str,
    timeout: float,
    fail_after: str | None,
    postgres_container: str | None = None,
) -> None:
    with disposable_database(prefix="restaurantos_m6_image") as database:
        before = public_tables(database)
        if before:
            raise ImageCheckError(
                "New image smoke database is not empty before startup"
            )
        suffix = uuid4().hex
        container_name = f"restaurantos-image-{suffix}"
        network_name = f"restaurantos-image-net-{suffix}"
        postgres_alias = f"m6-postgres-{suffix[:12]}"
        network_created = False
        postgres_connected = False
        container_attempted = False
        try:
            run_docker(
                ["network", "create", network_name],
                description="smoke network creation",
            )
            network_created = True
            if postgres_container:
                run_docker(
                    [
                        "network",
                        "connect",
                        "--alias",
                        postgres_alias,
                        network_name,
                        postgres_container,
                    ],
                    description="PostgreSQL smoke network attachment",
                )
                postgres_connected = True
            environment = production_environment(
                database,
                postgres_host=postgres_alias if postgres_container else None,
            )
            print(
                f"Starting smoke container {container_name} on disposable network {network_name}",
                flush=True,
            )
            container_attempted = True
            container_id = create_container(
                image=image,
                name=container_name,
                network=network_name,
                environment=environment,
                use_host_gateway=postgres_container is None,
            )
            port = published_port(container_id)
            wait_for_health(container_id, port, timeout, sensitive_values(environment))
            verify_container_database_connection(container_id, environment)
            after = public_tables(database)
            if after != before or "alembic_version" in after:
                raise ImageCheckError(
                    f"Image startup changed the database schema unexpectedly: {after}"
                )
            print(
                "PASS: image startup did not migrate or change the disposable database",
                flush=True,
            )
            inject_failure(
                "healthy", fail_after, container_name, network_name, database.name
            )
        finally:
            remove_resources(
                container_name if container_attempted else None,
                network_name if network_created else None,
                postgres_container if postgres_connected else None,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help=f"Image tag to build and smoke-test (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="Seconds to wait for the production health endpoint (default: 60)",
    )
    parser.add_argument(
        "--postgres-container",
        help="Running Docker Compose postgres container ID for direct isolated-network access",
    )
    parser.add_argument(
        "--inject-failure-after",
        choices=("healthy",),
        help="Intentionally fail after the smoke checks to exercise resource cleanup",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        print("FAIL: --timeout must be positive", file=sys.stderr)
        return 2
    try:
        read_test_url()
        run_docker(["info"], description="daemon check")
        postgres_container = (
            validate_postgres_container(args.postgres_container)
            if args.postgres_container
            else None
        )
        build_image(args.image)
        inspect_image(args.image)
        run_smoke(
            args.image,
            args.timeout,
            args.inject_failure_after,
            postgres_container,
        )
    except ImageCheckError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except (OSError, psycopg.Error, ValueError, subprocess.SubprocessError) as exc:
        print(
            f"FAIL: image check could not complete ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 1
    print(
        "PASS: backend production image build and runtime smoke check completed",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
