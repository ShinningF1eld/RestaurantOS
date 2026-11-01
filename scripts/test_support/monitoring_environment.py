"""Own monitoring resources explicitly; never attach to application resources."""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def command(*args: str, timeout: int = 180) -> str:
    result = subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        # Never echo arbitrary Docker output: it can contain runtime configuration.
        raise RuntimeError(f"{args[0]} command failed (exit {result.returncode})")
    return result.stdout.strip()


def require_local_engine() -> None:
    context = os.environ.get("DOCKER_CONTEXT")
    if context:
        endpoint = command(
            "docker",
            "context",
            "inspect",
            context,
            "--format",
            "{{.Endpoints.docker.Host}}",
        )
    else:
        endpoint = os.environ.get("DOCKER_HOST") or command(
            "docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
        )
    if not endpoint.startswith(("unix://", "npipe:////./pipe/")):
        raise RuntimeError("Monitoring lifecycle requires a local Docker engine")
    if command("docker", "info", "--format", "{{.OSType}}") != "linux":
        raise RuntimeError("Monitoring requires Linux containers")


def wait_until(check, timeout: int = 180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Monitoring check exceeded its readiness/query deadline")


class Monitoring:
    def __init__(self, directory: Path):
        if directory.is_symlink():
            raise ValueError("State directory must not be a symlink")
        self.directory = directory.resolve()
        self.state = json.loads((self.directory / "state.json").read_text())
        expected = "test" if self.state["ephemeral"] else "dev"
        if not re.fullmatch(
            f"restaurantos-monitoring-{expected}-[a-f0-9]{{16}}", self.state["project"]
        ):
            raise ValueError("Invalid monitoring resource ownership identity")
        if self.state["directory"] != str(self.directory):
            raise ValueError("State ownership path mismatch")
        if self.state["mode"] not in {"host", "container"}:
            raise ValueError("Invalid monitoring connection mode")

    @classmethod
    def initialize(
        cls,
        directory: Path,
        *,
        ephemeral: bool = False,
        mode: str = "host",
        grafana_port: int = 3001,
        otlp_port: int = 4318,
    ) -> Monitoring:
        if directory.exists() or directory.is_symlink():
            raise ValueError("State already exists; credentials are never overwritten")
        if mode not in {"host", "container"} or any(
            not 0 <= port <= 65535 for port in (grafana_port, otlp_port)
        ):
            raise ValueError("Invalid mode or port")
        directory.mkdir(mode=0o700, parents=True)
        directory = directory.resolve()
        if os.name == "nt":
            identity = command("whoami")
            command(
                "icacls",
                str(directory),
                "/inheritance:r",
                "/grant:r",
                identity + ":(OI)(CI)F",
            )
        state = {
            "version": 1,
            "project": "restaurantos-monitoring-"
            + ("test-" if ephemeral else "dev-")
            + uuid4().hex[:16],
            "directory": str(directory),
            "ephemeral": ephemeral,
            "mode": mode,
            "grafana_port": grafana_port,
            "otlp_port": otlp_port,
        }
        for name, value in (
            ("grafana_admin_user", "operator"),
            ("grafana_admin_password", secrets.token_urlsafe(48)),
        ):
            path = directory / name
            path.write_text(value)
            # Parent stays 0700 on host. Mounted file must be readable by UID 472.
            path.chmod(0o444)
        manifest = directory / "state.json"
        manifest.write_text(json.dumps(state, indent=2) + "\n")
        manifest.chmod(0o600)
        return cls(directory)

    @property
    def project(self) -> str:
        return self.state["project"]

    def compose(self, *args: str) -> str:
        removes_volumes = any(
            arg.split("=", 1)[0] == "--volumes"
            or (arg.startswith("-") and not arg.startswith("--") and "v" in arg)
            for arg in args[1:]
        )
        if args[0] == "down" and removes_volumes and not self.state["ephemeral"]:
            raise ValueError("Refusing to delete persistent development volumes")
        files = [ROOT / "monitoring/compose.yaml"]
        if self.state["mode"] == "host":
            files.append(ROOT / "monitoring/compose.host.yaml")
        else:
            # UI is loopback-only; OTLP stays entirely inside the acceptance network.
            overlay = self.directory / "container.yaml"
            overlay.write_text(
                "services:\n  grafana:\n    networks: [monitoring, host_ingress]\n"
                "    ports:\n      - target: 3000\n        published: '0'\n"
                "        host_ip: 127.0.0.1\nnetworks:\n  host_ingress:\n"
                "    driver: bridge\n"
            )
            files.append(overlay)
        override = self.directory / "override.yaml"
        if override.exists():
            files.append(override)
        cmd = ["docker", "compose", "--project-name", self.project]
        for file in files:
            cmd.extend(["-f", str(file)])
        env = {
            **os.environ,
            "MONITORING_STATE_DIR": str(self.directory),
            "MONITORING_GRAFANA_PORT": str(self.state["grafana_port"]),
            "MONITORING_OTLP_HTTP_PORT": str(self.state["otlp_port"]),
        }
        result = subprocess.run(
            [*cmd, *args],
            env=env,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180 if args[0] == "up" else 90,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"Monitoring Compose {args[0]} failed ({result.returncode})"
            )
        return result.stdout.strip()

    def container(self, service: str) -> str:
        if service not in {"collector", "prometheus", "grafana", "loki", "tempo"}:
            raise ValueError("Unknown monitoring service")
        return self.compose("ps", "--all", "-q", service)

    def port(self, service: str, target: int) -> int:
        output = self.compose("port", service, str(target))
        port = int(output.rsplit(":", 1)[1])
        if not 0 < port <= 65535:
            raise RuntimeError("No usable loopback port binding")
        return port

    def grafana(self, path: str, *, authenticated: bool = True):
        headers = {}
        if authenticated:
            user = (self.directory / "grafana_admin_user").read_text()
            password = (self.directory / "grafana_admin_password").read_text()
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            headers["Authorization"] = "Basic " + token
        request = Request(
            f"http://127.0.0.1:{self.port('grafana', 3000)}" + path, headers=headers
        )
        with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
            return json.load(response)

    def query(self, store: str, path: str):
        if store not in {"prometheus", "loki", "tempo"}:
            raise ValueError("Unknown data source")
        return self.grafana("/api/datasources/proxy/uid/restaurantos-" + store + path)

    def internal(self, url: str) -> str:
        return command(
            "docker",
            "exec",
            self.container("prometheus"),
            "/bin/wget",
            "-q",
            "-T",
            "3",
            "-O",
            "-",
            url,
            timeout=10,
        )

    def up(self) -> None:
        require_local_engine()
        self.compose("up", "-d")
        wait_until(lambda: self.grafana("/api/health"))
        for url in (
            "http://collector:13133/",
            "http://loki:3100/ready",
            "http://tempo:3200/ready",
        ):
            wait_until(lambda url=url: self.internal(url))
        for uid in ("prometheus", "loki", "tempo"):
            wait_until(
                lambda uid=uid: (
                    self.grafana(
                        "/api/datasources/uid/restaurantos-" + uid + "/health"
                    )["status"]
                    == "OK"
                )
            )

    def down(self, *, remove_volumes: bool = False) -> None:
        if remove_volumes and (
            not self.state["ephemeral"]
            or not self.project.startswith("restaurantos-monitoring-test-")
        ):
            raise ValueError("Refusing to delete persistent development volumes")
        require_local_engine()
        self.compose(
            "down", *(["--volumes"] if remove_volumes else []), "--remove-orphans"
        )
        kinds = ["container", "network"] + (["volume"] if remove_volumes else [])
        for kind in kinds:
            if command(
                "docker",
                kind,
                "ls",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + self.project,
            ):
                raise RuntimeError("Owned monitoring cleanup incomplete")


@contextmanager
def disposable_monitoring(mode: str = "host"):
    require_local_engine()
    with tempfile.TemporaryDirectory(
        prefix="restaurantos-monitoring-test-"
    ) as temporary:
        stack = Monitoring.initialize(
            Path(temporary) / "state",
            ephemeral=True,
            mode=mode,
            grafana_port=0,
            otlp_port=0,
        )
        try:
            yield stack
        finally:
            stack.down(remove_volumes=True)
