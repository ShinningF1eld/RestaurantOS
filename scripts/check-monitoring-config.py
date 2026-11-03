"""Validate monitoring configuration with pinned binaries, without service startup."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import yaml
from test_support.monitoring_environment import require_local_engine

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "collector": ("otel-collector.yaml", None, ["validate", "--config=/config.yaml"]),
    "prometheus": (
        "prometheus.yaml",
        "/bin/promtool",
        ["check", "config", "/config.yaml"],
    ),
    "loki": ("loki.yaml", None, ["-config.file=/config.yaml", "-verify-config=true"]),
    "tempo": ("tempo.yaml", None, ["-config.file=/config.yaml", "-config.verify=true"]),
}


def main() -> None:
    require_local_engine()
    lock = json.loads((ROOT / "monitoring/images.lock.json").read_text())
    compose = yaml.safe_load((ROOT / "monitoring/compose.yaml").read_text())
    for service, (filename, entrypoint, arguments) in CASES.items():
        image = lock["images"][service]["reference"]
        if compose["services"][service]["image"] != image:
            raise RuntimeError(f"{service}: Compose image differs from the lock")
        source = ROOT / "monitoring" / filename
        if not source.is_file():
            raise RuntimeError(f"{service}: missing configuration {filename}")
        memory = str(compose["services"][service]["mem_limit"])
        name = f"restaurantos-monitoring-config-{uuid4().hex}"
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--memory",
            memory,
            "--memory-swap",
            memory,
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "--mount",
            f"type=bind,src={source},dst=/config.yaml,readonly",
        ]
        if entrypoint:
            command.extend(["--entrypoint", entrypoint])
        try:
            subprocess.run([*command, image, *arguments], check=True, timeout=120)
        finally:
            # Also remove a container whose parser or image fetch timed out.
            # Never select by a shared prefix or touch another Compose project.
            cleanup = subprocess.run(
                ["docker", "rm", "--force", "--volumes", name],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if cleanup.returncode and "No such container" not in cleanup.stderr:
                raise RuntimeError(f"{service}: parser container cleanup failed")
        if service == "collector":
            with tempfile.TemporaryDirectory(
                prefix="restaurantos-receiver-config-"
            ) as folder:
                secret = Path(folder) / "password"
                secret.write_text("parser-only")
                secret.chmod(0o444)
                extra = [
                    "--env",
                    "MONITORING_POSTGRES_ENDPOINT=localhost:5432",
                    "--env",
                    "MONITORING_POSTGRES_DATABASE=parser_test",
                    "--env",
                    "MONITORING_REDIS_ENDPOINT=localhost:6379",
                    "--mount",
                    f"type=bind,src={ROOT / 'monitoring/otel-diagnostics.yaml'},dst=/diagnostics.yaml,readonly",
                    "--mount",
                    f"type=bind,src={secret},dst=/run/secrets/postgres_monitor_password,readonly",
                    "--mount",
                    f"type=bind,src={secret},dst=/run/secrets/redis_monitor_password,readonly",
                ]
                try:
                    subprocess.run(
                        [
                            *command,
                            *extra,
                            image,
                            *arguments,
                            "--config=/diagnostics.yaml",
                        ],
                        check=True,
                        timeout=120,
                    )
                finally:
                    cleanup = subprocess.run(
                        ["docker", "rm", "--force", "--volumes", name],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    if cleanup.returncode and "No such container" not in cleanup.stderr:
                        raise RuntimeError("Receiver parser cleanup failed")
        print(
            f"PASS: {service} configuration (locked image, network disabled)",
            flush=True,
        )
    print(
        "Parser checks only; startup, ingestion, retention and resource fit are separate."
    )


if __name__ == "__main__":
    main()
