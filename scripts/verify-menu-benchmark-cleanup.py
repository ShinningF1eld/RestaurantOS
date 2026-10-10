"""Prove real injected benchmark failures clean their owned test resources."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url
from validate import services

ROOT = Path(__file__).resolve().parents[1]


def owned_redis_names() -> set[str]:
    result = subprocess.check_output(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=restaurantos-auth-outage-",
            "--format",
            "{{.Names}}",
        ],
        text=True,
    )
    return set(result.splitlines())


def main() -> None:
    (ROOT / "test-results").mkdir(exist_ok=True)
    with (
        services(False) as environment,
        tempfile.TemporaryDirectory(
            prefix="issue27-benchmark-cleanup-", dir=ROOT / "test-results"
        ) as temporary,
    ):
        template = make_url(environment["TEST_DATABASE_URL"]).set(
            drivername="postgresql"
        )
        admin = template.set(database="postgres").render_as_string(hide_password=False)
        for stage in ("seed", "measurement", "request"):
            before = owned_redis_names()
            log = ROOT / "test-results" / f"issue27-injected-{stage}.log"
            output = Path(temporary) / stage
            # Hostile settings are safe sentinels; the explicit loader must ignore
            # them, including invalid inherited JSON, not parse developer config.
            isolated = {
                **environment,
                "DATABASE_URL": "postgresql+asyncpg://developer.invalid/do_not_touch",
                "REDIS_URL": "redis://developer.invalid:6379/0",
                "AUTH_TRUSTED_ORIGINS": "invalid-json",
                "AUTH_TRUSTED_PROXY_IPS": "invalid-json",
                "AUTH_ACCESS_SECONDS": "1",
            }
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    [
                        sys.executable,
                        "scripts/benchmark-menu-reads.py",
                        "--cache-state",
                        "warm",
                        "--requests",
                        "20",
                        "--warmup",
                        "0",
                        "--repetitions",
                        "1",
                        "--concurrency",
                        "1",
                        "--scenarios",
                        "menu-list",
                        "--output-dir",
                        str(output),
                        "--inject-failure-after",
                        stage,
                    ],
                    cwd=ROOT,
                    env=isolated,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            if result.returncode != 1:
                raise RuntimeError(
                    f"Injected {stage} failure did not return expected exit 1"
                )
            if list(output.glob("*.json")) or list(output.glob("*.tmp")):
                raise RuntimeError("Failed benchmark retained a result artifact")
            with psycopg.connect(admin) as connection:
                count = connection.execute(
                    "SELECT count(*) FROM pg_database WHERE datname LIKE 'restaurantos_benchmark_%_test'"
                ).fetchone()[0]
            if count:
                raise RuntimeError("Failed benchmark retained an allocated database")
            with psycopg.connect(
                template.render_as_string(hide_password=False)
            ) as connection:
                if (
                    connection.execute(
                        "SELECT to_regclass('public.alembic_version')"
                    ).fetchone()[0]
                    is not None
                ):
                    raise RuntimeError("Benchmark migrated its connection template")
            if owned_redis_names() - before:
                raise RuntimeError("Failed benchmark retained its Redis container")
            print(
                f"{stage}: expected exit 1, zero artifacts/databases/new Redis containers; template unmigrated",
                flush=True,
            )
    print("All injected failures and owned Compose cleanup passed", flush=True)


if __name__ == "__main__":
    main()
