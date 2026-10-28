"""Disposable Chromium/container gateway matrix; no developer DB or machine trust."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / ".local-gateway"
CREATE_USER = """
import asyncio,json,sys
from app.modules.auth.cli import create_user
from app.db.database import engine
async def main():
    c=json.load(sys.stdin)
    try: await create_user(c['email'],c['password'])
    finally: await engine.dispose()
asyncio.run(main())
"""
EXPIRE_ACCESS = """
import json,sys,time,jwt
from app.core.config import get_settings
s=get_settings()
payload=jwt.decode(json.load(sys.stdin)['token'],s.auth_jwt_secret.get_secret_value(),algorithms=['HS256'],audience=s.auth_jwt_audience,issuer=s.auth_jwt_issuer)
assert payload['token_use']=='access'
payload.update(iat=int(time.time())-60,exp=int(time.time())-1)
print(json.dumps({'token':jwt.encode(payload,s.auth_jwt_secret.get_secret_value(),algorithm='HS256')}))
"""
PROBE_HOOK = """
# Mounted only by the disposable runner; never copied into application images.
import json,logging
from pathlib import Path
from app.modules.auth import dependencies
original = dependencies.client_ip
def observed(request):
    resolved = original(request)
    label = request.headers.get('x-gateway-probe')
    if label in {'A','B','C'}:
        data=json.loads(Path('/gateway-probe/sources.json').read_text())
        source=data['sources'].get(label)
        peer=source if label=='C' else data['proxy']
        logging.getLogger('gateway_test_probe').info(
            'gateway_probe|%s|%s|%s',label,
            int(request.client.host==peer),int(resolved==source))
    return resolved
dependencies.client_ip=observed
"""
PEER_CLIENT = """
import http.client,json,socket,ssl,sys
data=json.load(sys.stdin)
class Edge(http.client.HTTPSConnection):
    def connect(self):
        self.sock=self._context.wrap_socket(socket.create_connection(('caddy',443),timeout=10),server_hostname='localhost')
label=data['label']; origin=data['origin']
connection=http.client.HTTPConnection('api',8000,timeout=10) if label=='C' else Edge('localhost',context=ssl.create_default_context(cafile='/ca.crt'),timeout=10)
def login(body,forged=False):
    headers={'Host':origin.split('://')[1],'Origin':origin,'X-CSRF-Protection':'1','Content-Type':'application/json','X-Gateway-Probe':label}
    if forged: headers.update({'X-Forwarded-For':'203.0.113.1' if forged==1 else '203.0.113.1, 203.0.113.2','Forwarded':'for=203.0.113.3','X-Real-IP':'203.0.113.4','X-Forwarded-Host':'forged.invalid','X-Forwarded-Proto':'http'})
    connection.request('POST','/auth/login' if label=='C' else '/backend/auth/login',json.dumps(body),headers)
    response=connection.getresponse(); raw=response.read()
    return response.status,response.getheaders()
def refresh(token):
    headers={'Host':origin.split('://')[1],'Origin':origin,'X-CSRF-Protection':'1','Cookie':'ros_refresh='+token,'X-Gateway-Probe':label}
    connection.request('POST','/backend/auth/refresh',b'',headers)
    r=connection.getresponse(); r.read()
    token=next((v.split(';',1)[0].split('=',1)[1] for k,v in r.getheaders() if k.lower()=='set-cookie' and v.startswith('ros_refresh=')),None)
    return r.status,token
def token_from(cookies):
    return next(v.split(';',1)[0].split('=',1)[1] for k,v in cookies if k.lower()=='set-cookie' and v.startswith('ros_refresh='))
mode=data['mode']; credentials=data['credentials']
if mode=='failures':
    statuses=[login({'email':credentials['email'],'password':credentials['password']+'-wrong'},index%2+1)[0] for index in range(data['count'])]
elif mode=='refresh':
    tokens=[]
    for _ in range(11):
        code,cookies=login(credentials)
        assert code==200
        tokens.append(token_from(cookies))
    statuses=[]
    for index in range(10):
        for _ in range(10):
            code,tokens[index]=refresh(tokens[index]); statuses.append(code)
    statuses.append(refresh(tokens[10])[0])
else:
    code,cookies=login(credentials,True)
    assert code==200
    statuses=[refresh(token_from(cookies))[0]]
connection.close()
print(json.dumps({'statuses':statuses}))
"""


def helper_for(name: str):
    if not re.fullmatch(r"browser-[0-9a-f]{12}", name):
        raise RuntimeError("Only freshly owned browser-run state is accepted")
    spec = importlib.util.spec_from_file_location(
        "gateway_helper", ROOT / "scripts/local-gateway.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.STATE = BASE / name
    return helper


def save(helper, state: dict) -> None:
    (helper.STATE / "state.json").write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )


def fixture(helper, action: str, data: dict) -> dict:
    state = helper.load()
    if state.get("browser_run") is not True:
        raise RuntimeError("Fixture controls require a disposable browser marker")
    if action == "database":
        if type(data.get("paused")) is not bool:
            raise ValueError("Database pause requires an explicit boolean")
        helper.compose(state, "pause" if data["paused"] else "unpause", "postgres")
        return {"ok": True}
    if action == "create":
        helper.compose(
            state,
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            CREATE_USER,
            input_text=json.dumps(data),
        )
        return {"ok": True}
    if action == "expire":
        return json.loads(
            helper.compose(
                state,
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                EXPIRE_ACCESS,
                input_text=json.dumps(data),
            )
        )
    if action == "restart":
        helper.compose(state, "down")
        with contextlib.redirect_stdout(io.StringIO()):
            helper.start(state)
        return {"ok": True}
    if action == "receipt":
        restaurant, menu = int(data["restaurant"]), int(data["menu"])
        if restaurant <= 0 or menu <= 0:
            raise ValueError("Invalid synthetic resource")
        query = f"SELECT count(*) FROM event_receipts r JOIN outbox_events e USING(event_id) JOIN event_diagnostics d USING(event_id) WHERE e.restaurant_id={restaurant} AND e.aggregate_type='menu' AND e.aggregate_id='{menu}' AND e.aggregate_revision=1 AND r.consumer_name='notification_sink' AND d.organization_id=e.organization_id AND d.restaurant_id=e.restaurant_id"
        count = helper.compose(
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
        return {"count": int(count)}
    if action == "privacy":
        logs = helper.compose(
            state, "logs", "--no-color", "api", "frontend", "worker", "caddy"
        )
        return {
            "clean": all(value not in logs for value in data["secrets"] if value)
            and re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", logs)
            is None
        }
    if action == "identity":
        return identity_check(helper, state, data)
    raise ValueError("Unknown fixture")


def install_probe(helper, state: dict) -> None:
    for name, content in (
        ("sitecustomize.py", PROBE_HOOK),
        ("sources.json", json.dumps({"proxy": state["proxy_ip"], "sources": {}})),
    ):
        helper.write_private(helper.STATE / name, content)
        (helper.STATE / name).chmod(0o644)
    helper.write_private(
        helper.STATE / "probe.override.yaml",
        f"""services:
  api:
    environment:
      PYTHONPATH: /gateway-probe:/app
    volumes:
      - type: bind
        source: {helper.STATE.as_posix()}/sitecustomize.py
        target: /gateway-probe/sitecustomize.py
        read_only: true
      - type: bind
        source: {helper.STATE.as_posix()}/sources.json
        target: /gateway-probe/sources.json
        read_only: true
""",
    )


def identity_check(helper, state: dict, data: dict) -> dict:
    names, addresses = {}, {}
    try:
        for label in ("A", "B", "C"):
            name = state["project"] + "-peer-" + label.lower()
            names[label] = name
            network = state["project"] + ("_ssr_api" if label == "C" else "_edge_web")
            helper.docker(
                "run",
                "--detach",
                "--name",
                name,
                "--network",
                network,
                "--mount",
                "type=bind,source="
                + str(helper.STATE / "root.crt")
                + ",target=/ca.crt,readonly",
                "--entrypoint",
                "python",
                state["backend_image"],
                "-c",
                "import time; time.sleep(300)",
            )
            info = json.loads(helper.docker("inspect", name))[0]
            addresses[label] = info["NetworkSettings"]["Networks"][network]["IPAddress"]
        if len(set(addresses.values())) != 3:
            raise RuntimeError("Controlled source peers are not distinct")
        (helper.STATE / "sources.json").write_text(
            json.dumps({"proxy": state["proxy_ip"], "sources": addresses}),
            encoding="utf-8",
        )
        while 60 - time.time() % 60 < 35:
            time.sleep(0.5)
        window = int(time.time() // 60)

        def run(label, mode, credentials, count=1):
            return json.loads(
                helper.docker(
                    "exec",
                    "-i",
                    names[label],
                    "python",
                    "-c",
                    PEER_CLIENT,
                    input_text=json.dumps(
                        {
                            "label": label,
                            "mode": mode,
                            "credentials": credentials,
                            "count": count,
                            "origin": data["origin"],
                        }
                    ),
                )
            )["statuses"]

        assert run("A", "failures", data["login"], 6) == [401] * 5 + [429]
        assert run("B", "failures", data["login"]) == [401]
        assert run("C", "failures", data["login"]) == [401]
        assert run("A", "refresh", data["refresh"]) == [200] * 100 + [429]
        assert run("B", "one-refresh", data["refresh"]) == [200]
        assert int(time.time() // 60) == window, (
            "Controlled quota batch crossed its fixed window"
        )
        logs = helper.compose(state, "logs", "--no-color", "api")
        for label in ("A", "B", "C"):
            assert "gateway_probe|" + label + "|1|1" in logs
            assert "gateway_probe|" + label + "|0" not in logs
            assert "gateway_probe|" + label + "|1|0" not in logs
        return {
            "distinct_peers": True,
            "login_isolated": True,
            "refresh_isolated": True,
            "peer_and_resolved_identity_match": True,
            "same_fixed_window": True,
        }
    finally:
        for name in names.values():
            helper.docker("rm", "--force", name)


def cleanup(helper, state: dict) -> None:
    path = helper.STATE.resolve()
    if (
        BASE.resolve() != BASE
        or helper.STATE.is_symlink()
        or getattr(helper.STATE, "is_junction", lambda: False)()
        or path.parent != BASE.resolve()
        or not re.fullmatch(r"browser-[0-9a-f]{12}", path.name)
    ):
        raise RuntimeError("Refusing cleanup outside the owned browser-run directory")
    if state.get("browser_run") is not True:
        raise RuntimeError("Refusing volume cleanup without ephemeral ownership")
    if state.get("backend_image") and state.get("frontend_image"):
        # A failed readiness probe can leave the owned database suspended.
        database = helper.compose(state, "ps", "--all", "--quiet", "postgres")
        if (
            database
            and helper.docker("inspect", "--format", "{{.State.Paused}}", database)
            == "true"
        ):
            helper.compose(state, "unpause", "postgres")
        helper.compose(state, "down", "--volumes", "--remove-orphans")
    for command in (("ps", "-aq"), ("volume", "ls", "-q"), ("network", "ls", "-q")):
        if helper.docker(
            *command, "--filter", "label=com.docker.compose.project=" + state["project"]
        ):
            raise RuntimeError("Owned browser resources remain")
    shutil.rmtree(path)


def startup_diagnostics(helper, state: dict) -> dict:
    """Only structural state and fixed failure labels; never raw logs/settings."""
    result = {}
    markers = (
        "permission denied",
        "read-only file system",
        "not a directory",
        "connection refused",
        "timed out",
        "503",
        "404",
        "modulenotfounderror",
        "validationerror",
    )
    for service in ("postgres", "redis", "api", "worker", "frontend", "caddy"):
        with contextlib.suppress(Exception):
            container = helper.compose(state, "ps", "--all", "--quiet", service)
            if not container:
                continue
            current = json.loads(
                helper.docker("inspect", "--format", "{{json .State}}", container)
            )
            health = current.get("Health", {})
            output = " ".join(item.get("Output", "") for item in health.get("Log", []))
            output += str(current.get("Error", ""))
            result[service] = {
                "status": current.get("Status"),
                "exit_code": current.get("ExitCode"),
                "oom_killed": current.get("OOMKilled"),
                "health": health.get("Status"),
                "failure_labels": [
                    marker for marker in markers if marker in output.lower()
                ],
            }
    return result


def run_matrix(inject: bool) -> int:
    BASE.mkdir(mode=0o700, exist_ok=True)
    name = "browser-" + secrets.token_hex(6)
    helper = helper_for(name)
    helper.require_local_engine()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    state = None
    report = ROOT / "test-results/gateway-browser" / name
    report.mkdir(parents=True)
    try:
        helper.initialize(port)
        state = helper.load()
        state["browser_run"] = True
        state["host_architecture"] = platform.machine().lower()
        state["docker_architecture"] = helper.docker(
            "info", "--format", "{{.Architecture}}"
        )
        save(helper, state)
        install_probe(helper, state)
        helper.build(state)
        save(helper, state)
        helper.migrate(state)
        try:
            helper.start(state)
        except Exception:
            evidence = startup_diagnostics(helper, state)
            (report / "startup.json").write_text(
                json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
            )
            print("Gateway startup state: " + json.dumps(evidence), flush=True)
            raise
        # Reuse the real stack assertions for applied limits, private exposure,
        # pool budgets and identical API/worker image identity on either host.
        helper.check_runtime(state)
        state["runtime_configuration_verified"] = True
        expected_architecture = {
            "x86_64": "amd64",
            "aarch64": "arm64",
            "arm64": "arm64",
        }[state["docker_architecture"]]
        for image in (state["backend_image"], state["frontend_image"]):
            if (
                helper.docker(
                    "image", "inspect", "--format", "{{.Architecture}}", image
                )
                != expected_architecture
            ):
                raise RuntimeError("Application image architecture differs from engine")
        save(helper, state)
        env = {
            **os.environ,
            "GATEWAY_BROWSER_STATE": name,
            "GATEWAY_BROWSER_REPORT": str(report / "results.json"),
            "GATEWAY_BROWSER_PYTHON": sys.executable,
            "NODE_EXTRA_CA_CERTS": str(helper.STATE / "root.crt"),
            "NODE_TLS_REJECT_UNAUTHORIZED": "1",
            "DEBUG": "",
            "PWDEBUG": "0",
        }
        if inject:
            env["GATEWAY_BROWSER_INJECT_FAILURE"] = "1"
        process = subprocess.Popen(
            [shutil.which("node") or "node", str(ROOT / "scripts/gateway-browser.mjs")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name != "nt",
        )
        try:
            stdout, _ = process.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=20)
            raise RuntimeError(
                "Owned Chromium matrix timed out; process tree stopped"
            ) from None
        for line in stdout.splitlines():
            if re.fullmatch(r"(PASS|FAIL): [A-Za-z0-9 _-]+", line):
                print(line, flush=True)
        return process.returncode
    finally:
        if state:
            cleanup(helper, state)
            (report / "cleanup.json").write_text(
                '{"owned_resources_removed":true}\n', encoding="utf-8"
            )
            print("PASS: owned gateway browser resources removed", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        choices=(
            "create",
            "expire",
            "restart",
            "receipt",
            "privacy",
            "identity",
            "database",
        ),
    )
    parser.add_argument("--state")
    parser.add_argument("--inject-failure", action="store_true")
    args = parser.parse_args()
    try:
        if args.fixture:
            helper = helper_for(args.state or "")
            helper.require_local_engine()
            with helper.exclusive_operation():
                value = fixture(helper, args.fixture, json.load(sys.stdin))
            print(json.dumps(value))
            return 0
        return run_matrix(args.inject_failure)
    except (
        OSError,
        ValueError,
        RuntimeError,
        AssertionError,
        subprocess.SubprocessError,
    ) as error:
        # Preserve useful location evidence without exception text, input,
        # local variables or third-party tracebacks that might contain secrets.
        frames = [
            frame
            for frame in traceback.extract_tb(error.__traceback__)
            if Path(frame.filename).resolve().parent == ROOT / "scripts"
        ]
        location = (
            f" {Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else ""
        )
        print(
            f"FAIL: gateway browser runner {type(error).__name__}{location}", flush=True
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
