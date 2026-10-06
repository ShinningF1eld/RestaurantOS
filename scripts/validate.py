"""Shared local/CI quality gates. Default: all gates on disposable services."""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
GATES = (
    "baseline",
    "backend-static",
    "frontend-static",
    "backend-unit",
    "backend-integration",
    "frontend-tests",
    "frontend-build",
    "migrations",
    "browser",
    "image",
)
SERVICE_GATES = {"backend-integration", "migrations", "browser", "image"}


def run(*command, cwd=ROOT, env=None):
    subprocess.run(list(command), cwd=cwd, env=env, check=True)


@contextmanager
def services(external):
    if external:
        from test_support.disposable_postgres import read_test_url

        read_test_url()
        yield dict(os.environ)
        return
    project = "restaurantos-m6-" + uuid4().hex[:12]
    command = [
        "docker",
        "compose",
        "-f",
        str(ROOT / "docker-compose.test.yml"),
        "-p",
        project,
    ]
    try:
        run(*command, "up", "-d", "--wait", "--wait-timeout", "120")

        def port(service, number):
            result = subprocess.check_output(
                [*command, "port", service, str(number)], text=True
            )
            return int(result.strip().rsplit(":", 1)[1])

        env = {
            **os.environ,
            "TEST_DATABASE_URL": f"postgresql+asyncpg://restaurantos:restaurantos@127.0.0.1:{port('postgres', 5432)}/restaurantos_test",  # pragma: allowlist secret
            "TEST_REDIS_HOST": "127.0.0.1",
            "TEST_REDIS_PORT": str(port("redis", 6379)),
            "TEST_POSTGRES_CONTAINER": subprocess.check_output(
                [*command, "ps", "-q", "postgres"], text=True
            ).strip(),
        }
        yield env
    finally:
        run(*command, "down", "--volumes", "--remove-orphans")


def redis_check(env):
    host, port = (
        env.get("TEST_REDIS_HOST", "127.0.0.1"),
        int(env.get("TEST_REDIS_PORT", "6379")),
    )
    key = "restaurantos:m6:" + uuid4().hex
    with socket.create_connection((host, port), timeout=5) as connection:
        stream = connection.makefile("rb")

        def command(*parts):
            data = f"*{len(parts)}\r\n".encode()
            for part in parts:
                value = part.encode()
                data += f"${len(value)}\r\n".encode() + value + b"\r\n"
            connection.sendall(data)
            return stream.readline()

        if command("PING") != b"+PONG\r\n":
            raise RuntimeError("Redis infrastructure PING failed")
        try:
            if command("SET", key, "isolated", "EX", "30") != b"+OK\r\n":
                raise RuntimeError("Redis isolated write failed")
            if command("GET", key) != b"$8\r\n" or stream.read(10) != b"isolated\r\n":
                raise RuntimeError("Redis isolated read failed")
        finally:
            if command("DEL", key) not in {b":0\r\n", b":1\r\n"}:
                raise RuntimeError("Redis namespaced cleanup failed")
            if command("GET", key) != b"$-1\r\n":
                raise RuntimeError("Redis validation key survived cleanup")
    print("PASS: Redis infrastructure availability and namespaced cleanup")


def backend_tests(label, selectors, env):
    reports = Path("coverage") / label
    (BACKEND / reports).mkdir(parents=True, exist_ok=True)
    isolated = {**env, "COVERAGE_FILE": str(BACKEND / reports / ".coverage")}
    run(
        sys.executable,
        "-m",
        "pytest",
        *selectors,
        "--cov=app",
        "--cov-report=term-missing",
        f"--cov-report=xml:{reports}/coverage.xml",
        f"--cov-report=json:{reports}/coverage.json",
        f"--cov-report=html:{reports}/html",
        cwd=BACKEND,
        env=isolated,
    )


def gate(name, env):
    npm = shutil.which("npm") or "npm"
    python = sys.executable
    print(f"==> {name}", flush=True)
    if name == "baseline":
        run("docker", "compose", "config", "--quiet")
        run(python, "-m", "pip", "check")
        files = (
            subprocess.check_output(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                cwd=ROOT,
            )
            .decode()
            .split("\0")
        )
        hook = Path(python).parent / (
            "detect-secrets-hook.exe" if os.name == "nt" else "detect-secrets-hook"
        )
        # The hook can refresh line numbers in its baseline. Keep validation
        # non-mutating by giving it a disposable copy of the reviewed baseline.
        with tempfile.TemporaryDirectory(prefix="restaurantos-secret-check-") as folder:
            baseline = Path(folder) / ".secrets.baseline"
            shutil.copy2(ROOT / ".secrets.baseline", baseline)
            run(
                str(hook),
                "--baseline",
                str(baseline),
                *[f for f in files if f and f != ".secrets.baseline"],
            )
    elif name == "backend-static":
        run(python, "-m", "ruff", "check", "app", "tests", cwd=BACKEND)
        run(python, "-m", "ruff", "format", "--check", "app", "tests", cwd=BACKEND)
        run(python, "-m", "mypy", "app", cwd=BACKEND)
    elif name == "frontend-static":
        for script in ("lint", "format:check", "typecheck"):
            run(npm, "run", script, cwd=FRONTEND)
    elif name == "backend-unit":
        clean = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(
                (
                    "DATABASE",
                    "TEST_DATABASE",
                    "AUTH_",
                    "REDIS",
                    "TEST_REDIS",
                    "TEST_POSTGRES",
                )
            )
        }
        backend_tests("backend-unit", ["tests/unit"], clean)
    elif name == "backend-integration":
        from test_support.disposable_postgres import disposable_database

        redis_check(env)
        with disposable_database(
            prefix="restaurantos_integration", test_url=env["TEST_DATABASE_URL"]
        ) as database:
            isolated = database.environment(env)
            run(python, "-m", "alembic", "upgrade", "head", cwd=BACKEND, env=isolated)
            backend_tests(
                "backend-integration", ["tests", "--ignore=tests/unit"], isolated
            )
            run(python, "-m", "alembic", "check", cwd=BACKEND, env=isolated)
    elif name == "frontend-tests":
        for script in ("test:client:coverage", "test:component:coverage"):
            run(npm, "run", script, cwd=FRONTEND)
    elif name == "frontend-build":
        import runpy

        browser = runpy.run_path(str(ROOT / "scripts" / "run-browser-tests.py"))
        with browser["frontend_copy"]() as frontend:
            build_env = {**os.environ, "M6_SOURCE_ROOT": str(ROOT)}
            run(npm, "run", "build", cwd=frontend, env=build_env)
    elif name == "migrations":
        run(python, "scripts/verify-migrations.py", env=env)
    elif name == "browser":
        run(python, "scripts/run-browser-tests.py", env=env)
    elif name == "image":
        arguments = []
        if env.get("TEST_POSTGRES_CONTAINER"):
            arguments = ["--postgres-container", env["TEST_POSTGRES_CONTAINER"]]
        run(python, "scripts/check-backend-image.py", *arguments, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gate", choices=GATES, action="append", help="Explicit partial validation"
    )
    parser.add_argument(
        "--external-services",
        action="store_true",
        help="CI service containers; explicit TEST_DATABASE_URL required",
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="Use existing dependencies; marks result partial",
    )
    parser.add_argument(
        "--inject-failure",
        choices=GATES,
        help="Exercise nonzero propagation and cleanup",
    )
    args = parser.parse_args()
    selected = args.gate or list(GATES)
    partial = bool(args.gate or args.no_install)
    if partial:
        print(
            "PARTIAL validation; omitted gates:",
            ", ".join(g for g in GATES if g not in selected) or "none",
            "; locked installation omitted:",
            args.no_install,
            flush=True,
        )
    if not args.no_install:
        run(
            sys.executable,
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "-r",
            "requirements-dev.txt",
            cwd=BACKEND,
        )
        run(shutil.which("npm") or "npm", "ci", cwd=FRONTEND)

    def execute(env):
        for name in selected:
            if args.inject_failure == name:
                raise RuntimeError(
                    f"Intentional {name} failure for cleanup verification"
                )
            gate(name, env)

    if SERVICE_GATES.intersection(selected):
        with services(args.external_services) as env:
            execute(env)
    else:
        execute(dict(os.environ))
    print(
        "PASS: "
        + (
            "partial validation (not milestone acceptance)"
            if partial
            else "full validation"
        )
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(
            f"FAIL: validation subprocess returned {error.returncode}", file=sys.stderr
        )
        raise SystemExit(error.returncode) from None
