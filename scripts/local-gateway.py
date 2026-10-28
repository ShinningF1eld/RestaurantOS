"""Own an isolated synthetic HTTPS Compose rehearsal; never use the developer DB."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local-gateway"
COMPOSE = ROOT / "deploy/local/compose.yaml"


def diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    detail = result.stderr or result.stdout
    env_file = STATE / "backend.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if value and any(marker in key for marker in ("SECRET", "URL")):
                detail = detail.replace(value, "[REDACTED]")
    for name in ("postgres_password",):
        path = STATE / name
        if path.exists():
            detail = detail.replace(
                path.read_text(encoding="utf-8").strip(), "[REDACTED]"
            )
    redis_config = STATE / "redis.conf"
    if redis_config.exists():
        for line in redis_config.read_text(encoding="utf-8").splitlines():
            if line.startswith("requirepass "):
                detail = detail.replace(line.split(" ", 1)[1], "[REDACTED]")
    return detail[-4000:].strip()


def command(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        # Runtime commands may contain credentials on stdin or emit connection
        # URLs. Do not echo arbitrary stdout/stderr into retained diagnostics.
        raise RuntimeError(
            f"{args[0]} {args[1]} failed (exit {result.returncode}): {diagnostic(result)}"
        )
    return result.stdout.strip()


def docker(*args: str, input_text: str | None = None) -> str:
    return command("docker", *args, input_text=input_text)


def require_local_engine() -> None:
    endpoint = os.environ.get("DOCKER_HOST") or docker(
        "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
    )
    if not endpoint.startswith(("npipe:////./pipe/", "unix://")):
        raise RuntimeError(
            "Rehearsal requires a local Docker socket, never an SSH/TCP remote engine"
        )
    if docker("info", "--format", "{{.OSType}}") != "linux":
        raise RuntimeError("Rehearsal requires the Linux container engine")


def write_private(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    path.chmod(0o600)


def occupied_networks() -> list[ipaddress.IPv4Network]:
    networks = []
    ids = docker("network", "ls", "-q").split()
    if ids:
        for network in json.loads(docker("network", "inspect", *ids)):
            for entry in network.get("IPAM", {}).get("Config", []) or []:
                subnet = entry.get("Subnet", "")
                if subnet and ":" not in subnet:
                    networks.append(ipaddress.IPv4Network(subnet, strict=False))
    if os.name == "nt":
        routes = command("route", "print", "-4")
        for line in routes.splitlines():
            fields = line.split()
            if len(fields) < 4:
                continue
            try:
                route = ipaddress.IPv4Network(f"{fields[0]}/{fields[1]}", strict=False)
            except ValueError:
                continue
            if route.prefixlen:
                networks.append(route)
    else:
        routes = json.loads(command("ip", "-j", "-4", "route", "show", "table", "all"))
        for route in routes:
            destination = route.get("dst", "default")
            if destination != "default":
                networks.append(ipaddress.IPv4Network(destination, strict=False))
    return networks


def initialize(port: int) -> None:
    if STATE.exists():
        raise RuntimeError(
            ".local-gateway already exists; existing secrets are never replaced"
        )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    occupied = occupied_networks()
    subnet = None
    for _ in range(256):
        candidate = ipaddress.IPv4Network(
            f"10.{240 + secrets.randbelow(10)}.{secrets.randbelow(256)}.0/24"
        )
        if not any(candidate.overlaps(other) for other in occupied):
            subnet = candidate
            break
    if subnet is None:
        raise RuntimeError(
            "No unused rehearsal subnet found; inspect host/Docker routes"
        )
    STATE.mkdir(mode=0o700)
    protect_directory()
    config = {
        "version": 1,
        "project": "restaurantos-gateway-" + secrets.token_hex(6),
        "port": port,
        "subnet": str(subnet),
        "proxy_ip": str(subnet.network_address + 2),
    }
    password, redis_password = secrets.token_hex(32), secrets.token_hex(32)
    write_private(STATE / "postgres_password", password)
    write_private(
        STATE / "redis.conf",
        "\n".join(
            [
                "bind 0.0.0.0",
                "protected-mode yes",
                'save ""',
                "appendonly no",
                "maxmemory 128mb",
                "maxmemory-policy noeviction",
                f"requirepass {redis_password}",
                "",
            ]
        ),
    )
    backend = {
        "DATABASE_URL": f"postgresql+asyncpg://gateway:{password}@postgres:5432/restaurantos_gateway_test",
        "ENVIRONMENT": "production",
        "DATABASE_ECHO": "false",
        "DATABASE_POOL_SIZE": "5",
        "DATABASE_MAX_OVERFLOW": "0",
        "DATABASE_POOL_TIMEOUT_SECONDS": "5",
        "REDIS_URL": f"redis://:{redis_password}@redis:6379/0",
        "AUTH_JWT_SECRET": secrets.token_urlsafe(48),
        "AUTH_RATE_LIMIT_SECRET": secrets.token_urlsafe(48),
        "AUTH_COOKIE_SECURE": "true",
        "AUTH_REFRESH_COOKIE_PATH": "/backend/auth",
        "AUTH_TRUSTED_ORIGINS": json.dumps([f"https://localhost:{port}"]),
        "AUTH_TRUSTED_PROXY_IPS": json.dumps([config["proxy_ip"]]),
    }
    write_private(
        STATE / "backend.env",
        "\n".join(f"{key}={value}" for key, value in backend.items()) + "\n",
    )
    # The containing directory is private; bind mounts need container UID access.
    for name in ("backend.env", "redis.conf", "postgres_password"):
        (STATE / name).chmod(0o644)
    write_private(STATE / "state.json", json.dumps(config, indent=2) + "\n")
    print("Created isolated rehearsal configuration; secrets were not displayed.")


def protect_directory() -> None:
    if os.name == "nt":
        account = os.environ["USERDOMAIN"] + "\\" + os.environ["USERNAME"]
        command(
            "icacls",
            str(STATE),
            "/inheritance:r",
            "/grant:r",
            account + ":(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        )
    else:
        STATE.chmod(0o700)


def load() -> dict:
    if STATE.is_symlink() or STATE.resolve() != ROOT / ".local-gateway":
        raise RuntimeError("Refusing redirected rehearsal state directory")
    state = json.loads((STATE / "state.json").read_text(encoding="utf-8"))
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    if (STATE / "backend.env").resolve().parent != STATE:
        raise RuntimeError("Refusing redirected rehearsal configuration")
    config = dotenv_values(STATE / "backend.env", interpolate=False)
    try:
        url = make_url(config.get("DATABASE_URL") or "")
    except (ArgumentError, ValueError):
        raise RuntimeError("Invalid isolated rehearsal database URL") from None
    if (url.drivername, url.host, url.port, url.database, url.username) != (
        "postgresql+asyncpg",
        "postgres",
        5432,
        "restaurantos_gateway_test",
        "gateway",
    ):
        raise RuntimeError("Refusing any database outside the isolated gateway target")
    if state.get("version") != 1 or not re.fullmatch(
        r"restaurantos-gateway-[0-9a-f]{12}", state.get("project", "")
    ):
        raise RuntimeError("Invalid owned rehearsal project marker")
    if not isinstance(state.get("port"), int) or not 1024 <= state["port"] <= 65535:
        raise RuntimeError("Invalid rehearsal port")
    network = ipaddress.IPv4Network(state["subnet"])
    if (
        not network.is_private
        or network.prefixlen != 24
        or state["proxy_ip"] != str(network.network_address + 2)
    ):
        raise RuntimeError("Invalid proxy network identity")
    for key in ("backend_image", "frontend_image"):
        if key in state and not re.fullmatch(r"sha256:[0-9a-f]{64}", state[key]):
            raise RuntimeError("Invalid application image identity")
    return state


@contextmanager
def exclusive_operation():
    if STATE.resolve() != ROOT / ".local-gateway":
        raise RuntimeError("Refusing redirected rehearsal directory")
    lock = STATE / "operation.lock"
    try:
        write_private(lock, str(os.getpid()) + "\n")
    except FileExistsError:
        raise RuntimeError(
            "A rehearsal operation is active or interrupted; inspect operation.lock before recovery"
        ) from None
    try:
        yield
    finally:
        lock.unlink()


def compose(state: dict, *args: str, input_text: str | None = None) -> str:
    if not state.get("backend_image") or not state.get("frontend_image"):
        raise RuntimeError(
            "Build and record both application image IDs before Compose operations"
        )
    env = {
        **os.environ,
        "GATEWAY_STATE_DIR": str(STATE),
        "GATEWAY_HTTPS_PORT": str(state["port"]),
        "GATEWAY_PROXY_SUBNET": state["subnet"],
        "GATEWAY_PROXY_IP": state["proxy_ip"],
        "GATEWAY_API_IP": str(
            ipaddress.IPv4Network(state["subnet"]).network_address + 3
        ),
        "GATEWAY_BACKEND_IMAGE": state["backend_image"],
        "GATEWAY_FRONTEND_IMAGE": state["frontend_image"],
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            state["project"],
            "--file",
            str(COMPOSE),
            *args,
        ],
        cwd=ROOT,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"Compose {args[0]} failed (exit {result.returncode}): {diagnostic(result)}"
        )
    return result.stdout.strip()


def build(state: dict) -> None:
    for service, folder in (("backend", "backend"), ("frontend", "frontend")):
        tag = f"{state['project']}-{service}:local"
        print(f"Building {service} from the committed dependency locks", flush=True)
        docker(
            "build",
            "--pull",
            "--tag",
            tag,
            "--file",
            str(ROOT / folder / "Dockerfile"),
            str(ROOT / folder),
        )
        state[f"{service}_image"] = docker(
            "image", "inspect", "--format", "{{.Id}}", tag
        )
    # Do not alter secrets; only persist successfully built image identities.
    (STATE / "state.json").write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )


def migrate(state: dict) -> None:
    for service in ("api", "worker"):
        cid = compose(state, "ps", "-a", "-q", service)
        if cid:
            current = json.loads(docker("inspect", cid))[0]["State"]
            if current["Running"] or current.get("Restarting") or current.get("Paused"):
                raise RuntimeError(
                    "Stop API and worker before explicit rehearsal migrations"
                )
    compose(state, "up", "-d", "--wait", "postgres", "redis")
    compose(
        state,
        "run",
        "--rm",
        "--no-deps",
        "maintenance",
        "python",
        "-m",
        "alembic",
        "upgrade",
        "head",
    )
    print("Explicit migration completed on restaurantos_gateway_test only.")


def export_ca(state: dict) -> None:
    cid = compose(state, "ps", "-q", "caddy")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            cert = docker(
                "exec", cid, "cat", "/data/caddy/pki/authorities/local/root.crt"
            )
            (STATE / "root.crt").write_text(cert + "\n", encoding="ascii")
            return
        except RuntimeError:
            time.sleep(0.5)
    raise RuntimeError("Caddy local CA was not ready")


def start(state: dict) -> None:
    if "backend_image" not in state or "frontend_image" not in state:
        raise RuntimeError("Run build and migrate before up")
    compose(state, "config", "--quiet")
    compose(state, "up", "-d", "--wait", "postgres", "redis")
    actual = compose(
        state,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "gateway",
        "-d",
        "restaurantos_gateway_test",
        "-tAc",
        "SELECT version_num FROM alembic_version",
    )
    expected = compose(
        state,
        "run",
        "--rm",
        "--no-deps",
        "maintenance",
        "python",
        "-m",
        "alembic",
        "heads",
    ).split()[0]
    if actual.strip() != expected:
        raise RuntimeError(
            "Rehearsal schema does not match the image; stop writers and migrate explicitly"
        )
    # Recreating a network with an occupied subnet must fail, never change trust.
    compose(state, "up", "-d", "--wait", "--wait-timeout", "90")
    export_ca(state)
    print(
        f"Rehearsal started at https://localhost:{state['port']} (local CA required)."
    )


def check(state: dict, restart: bool) -> None:
    export_ca(state)
    ca_before = hashlib.sha256((STATE / "root.crt").read_bytes()).hexdigest()
    origin = f"https://localhost:{state['port']}"
    context = ssl.create_default_context(cafile=str(STATE / "root.crt"))
    jar = http.cookiejar.CookieJar()
    client = build_opener(
        ProxyHandler({}), HTTPSHandler(context=context), HTTPCookieProcessor(jar)
    )

    def request(path: str, body: dict | None = None, headers: dict | None = None):
        from urllib.request import Request

        supplied = {"Origin": origin, "X-CSRF-Protection": "1", **(headers or {})}
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            supplied["Content-Type"] = "application/json"
        try:
            with client.open(
                Request(origin + path, data=data, headers=supplied), timeout=10
            ) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            return error.code, error.headers, error.read()

    assert request("/")[0] == 200
    assert request("/backend/health")[0] == 200
    assert request("/backend/health/")[0] == 200
    assert request("/backend/docs")[0] == 404
    assert request("/backend/auth/me")[0] == 401
    assert (
        request("/backend/auth/login", {}, {"Origin": "https://untrusted.invalid"})[0]
        == 403
    )
    # Create an isolated synthetic account using the existing trusted CLI function.
    credentials = {
        "email": f"gateway-{secrets.token_hex(8)}@example.test",
        "password": secrets.token_urlsafe(32),
    }
    seed = """import asyncio,json,sys
from app.modules.auth.cli import create_user
from app.db.database import engine
async def main():
    c=json.load(sys.stdin)
    try: await create_user(c['email'],c['password'])
    finally: await engine.dispose()
asyncio.run(main())
"""
    compose(
        state,
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        seed,
        input_text=json.dumps(credentials),
    )
    status, headers, _ = request("/backend/auth/login", credentials)
    assert status == 200
    refresh_cookie = next(cookie for cookie in jar if cookie.name == "ros_refresh")
    assert refresh_cookie.path == "/backend/auth" and refresh_cookie.secure
    assert all(
        "HttpOnly" in value and "Secure" in value and "Domain=" not in value
        for value in headers.get_all("Set-Cookie")
    )
    assert request("/backend/auth/me")[0] == 200
    assert request("/backend/api/access/")[0] == 403  # no organization yet
    before = refresh_cookie.value
    assert request("/backend/auth/refresh", {})[0] == 200
    assert (
        next(cookie for cookie in jar if cookie.name == "ros_refresh").value != before
    )
    # Browser and SSR reach the same real API. Organization bootstrap uses the
    # existing service boundary through authenticated HTTP, never direct DB edits.
    status, _, payload = request(
        "/backend/api/organizations",
        {
            "name": "Gateway synthetic organization",
            "slug": "gateway-" + secrets.token_hex(8),
        },
    )
    assert status == 201, (status, "organization bootstrap failed")
    organization = json.loads(payload)
    marker = "Gateway synthetic " + secrets.token_hex(6)
    status, _, payload = request("/backend/api/restaurants", {"name": marker})
    assert status == 201
    restaurant_id = json.loads(payload)["id"]
    status, _, payload = request(
        f"/backend/restaurants/{restaurant_id}/menus", {"name": marker}
    )
    assert status == 200
    status, _, html = request(f"/restaurants/{restaurant_id}/menu")
    assert status == 200 and marker.encode() in html
    # Poll authoritative effect/receipt facts for this exact synthetic restaurant.
    query = f"SELECT count(*) FROM event_receipts r JOIN outbox_events e ON e.event_id=r.event_id WHERE e.restaurant_id={restaurant_id} AND e.event_type='menu.updated.v1' AND r.consumer_name='notification_sink'"
    deadline = time.monotonic() + 45
    while True:
        count = compose(
            state,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "gateway",
            "-d",
            "restaurantos_gateway_test",
            "-tAc",
            query,
        )
        if int(count) > 0:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Worker did not commit the synthetic menu event receipt")
        time.sleep(0.5)
    if restart:
        compose(state, "down")
        start(state)
        assert (
            hashlib.sha256((STATE / "root.crt").read_bytes()).hexdigest() == ca_before
        )
        assert request("/backend/auth/me")[0] == 200
        assert request("/backend/api/access")[0] == 200
        status, _, html = request(f"/restaurants/{restaurant_id}/menu")
        assert status == 200 and marker.encode() in html
        print(
            "PASS: session/tenant data, Caddy CA and fixed proxy identity survive down/up."
        )
    assert request("/backend/auth/logout", {})[0] == 204
    assert not any(cookie.name in {"ros_access", "ros_refresh"} for cookie in jar)
    assert request("/backend/auth/me")[0] == 401
    # Forging alternate client identity headers must not obtain a fresh pair
    # allowance. Use one newly generated synthetic account; sixth failure is 429.
    for attempt in range(6):
        status, _, _ = request(
            "/backend/auth/login",
            {
                **credentials,
                "password": credentials["password"] + "-incorrect",
            },
            {
                "X-Forwarded-For": "203.0.113.11" if attempt < 3 else "203.0.113.12",
                "Forwarded": "for=203.0.113.13",
                "X-Real-IP": "203.0.113.14",
            },
        )
        assert status == (401 if attempt < 5 else 429)
    # Inspect actual Docker settings, not only declarations in YAML.
    expected = {
        "caddy": (128, 128),
        "frontend": (640, 256),
        "api": (512, 256),
        "worker": (384, 128),
        "postgres": (1024, 128),
        "redis": (384, 128),
    }
    networks = {
        "caddy": {"edge_web", "edge_api"},
        "frontend": {"edge_web", "ssr_api"},
        "api": {"edge_api", "ssr_api", "data"},
        "worker": {"data"},
        "postgres": {"data"},
        "redis": {"data"},
    }
    for service, (memory, pids) in expected.items():
        cid = compose(state, "ps", "-q", service)
        info = json.loads(docker("inspect", cid))[0]
        assert info["HostConfig"]["Memory"] == memory * 1024 * 1024
        assert info["HostConfig"]["PidsLimit"] == pids
        assert info["HostConfig"]["CpuShares"] == {
            "api": 512,
            "postgres": 384,
            "frontend": 256,
        }.get(service, 128)
        assert info["HostConfig"]["LogConfig"] == {
            "Type": "json-file",
            "Config": {"max-size": "10m", "max-file": "3"},
        }
        if service in {"api", "worker", "frontend"}:
            assert info["HostConfig"]["ReadonlyRootfs"]
        assert set(info["NetworkSettings"]["Networks"]) == {
            state["project"] + "_" + network for network in networks[service]
        }
        bindings = info["HostConfig"].get("PortBindings") or {}
        if service == "caddy":
            assert bindings == {
                "443/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(state["port"])}]
            }
            assert (
                info["NetworkSettings"]["Networks"][state["project"] + "_edge_api"][
                    "IPAddress"
                ]
                == state["proxy_ip"]
            )
        else:
            assert not bindings
        if service in {"api", "worker"}:
            assert (
                info["Image"] == state["backend_image"]
                or info["Config"]["Image"] == state["backend_image"]
            )
    assert organization
    assert (
        compose(
            state,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "gateway",
            "-d",
            "restaurantos_gateway_test",
            "-tAc",
            "SHOW max_connections",
        ).strip()
        == "30"
    )
    compose(
        state,
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        "from app.db.database import engine; assert engine.pool.size()==5; assert engine.pool._max_overflow==0; assert engine.pool.timeout()==5",
    )
    compose(
        state,
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        "from app.core.config import get_settings; from redis import Redis; r=Redis.from_url(get_settings().redis_url.get_secret_value()); c=r.config_get('maxmemory*'); assert c['maxmemory-policy']=='noeviction'; assert int(c['maxmemory'])==128*1024*1024; r.close()",
    )
    print(
        "PASS: verified TLS, routing, cookie rotation/logout, CSRF, synthetic tenant bootstrap, limits and exposure."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("init", "build", "migrate", "up", "check", "down", "status")
    )
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument(
        "--restart", action="store_true", help="check persistence via owned down/up"
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    try:
        require_local_engine()
        if args.action == "init":
            initialize(args.port)
            return 0
        with exclusive_operation():
            state = load()
            if args.action == "build":
                build(state)
            elif args.action == "migrate":
                migrate(state)
            elif args.action == "up":
                start(state)
            elif args.action == "check":
                check(state, args.restart)
            elif args.action == "down":
                compose(state, "down")
            else:
                print(compose(state, "ps"))
    except (
        OSError,
        ValueError,
        RuntimeError,
        AssertionError,
        URLError,
        subprocess.SubprocessError,
    ) as error:
        if isinstance(error, AssertionError) and error.__traceback__:
            import traceback

            frame = traceback.extract_tb(error.__traceback__)[-1]
            error = AssertionError(
                f"check failed at {Path(frame.filename).name}:{frame.lineno}"
            )
        print(f"FAIL: local gateway {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
