"""Real authenticated SSR/API/Collector checks using existing isolated test owners."""

import argparse
import base64
import json
import runpy
import shutil
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

import requests
from sqlalchemy.engine import make_url
from test_support.disposable_postgres import disposable_database
from test_support.monitoring_environment import (
    ROOT,
    command,
    disposable_monitoring,
    wait_until,
)
from test_support.processes import stop_processes
from validate import services


def spans_in(trace):
    return [
        (batch["resource"], span)
        for batch in trace.get("batches", trace.get("resourceSpans", []))
        for scope in batch.get(
            "scopeSpans", batch.get("instrumentationLibrarySpans", [])
        )
        for span in scope["spans"]
    ]


def identifier(value):
    return value.lower() if len(value) in {16, 32} else base64.b64decode(value).hex()


def correlation(stack, trace_id):
    trace = stack.query("tempo", "/api/traces/" + trace_id)
    rows = spans_in(trace)
    frontend, api = [], []
    for resource, span in rows:
        service = next(
            a["value"].get("stringValue")
            for a in resource["attributes"]
            if a["key"] == "service.name"
        )
        (frontend if service == "restaurantos-frontend" else api).append(span)
    if not frontend or not api:
        return None
    clients = [s for s in frontend if s["name"] == "API request"]
    servers = [s for s in frontend if s["name"] == "Next.js request"]
    if not clients or not servers:
        return None
    by_id = {identifier(s["spanId"]): s for _, s in rows}
    assert len(by_id) == len(rows)
    if any(identifier(span["parentSpanId"]) not in by_id for span in api):
        return None  # Collector batches from different services can arrive separately.
    for span in api:
        assert identifier(span["traceId"]) == trace_id
        parent = by_id[identifier(span["parentSpanId"])]
        assert parent in clients
        # Client ancestry reaches a real Next server span, possibly via render spans.
        seen = set()
        while parent not in servers:
            key = identifier(parent["parentSpanId"])
            assert key not in seen
            seen.add(key)
            parent = by_id[key]
    return trace


def request(session, method, url, **kwargs):
    response = session.request(method, url, timeout=10, allow_redirects=False, **kwargs)
    return response


@contextmanager
def capture_exports(endpoint):
    """Inspect source OTLP in memory before Collector defense-in-depth filtering."""
    payloads = []

    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.path != "/v1/traces":
                self.send_error(400)
                return
            self.connection.settimeout(2)
            if self.headers.get("Transfer-Encoding") == "chunked":
                body = b""
                while True:
                    size = int(self.rfile.readline(128).strip(), 16)
                    if size == 0:
                        self.rfile.readline(128)
                        break
                    if len(body) + size > 65536:
                        self.send_error(413)
                        return
                    body += self.rfile.read(size)
                    assert self.rfile.read(2) == b"\r\n"
            else:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    self.send_error(400)
                    return
                body = self.rfile.read(length)
            payloads.append(body.decode())
            with requests.Session() as client:
                client.trust_env = False
                try:
                    result = client.post(
                        endpoint + "/v1/traces",
                        data=body,
                        headers={"Content-Type": "application/json"},
                        timeout=1,
                        allow_redirects=False,
                    )
                    status = result.status_code
                except requests.RequestException:
                    status = 503
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")
            except ConnectionError:
                pass  # Exporter timeout/process exit can close this synthetic connection.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", payloads
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("host", "container"), default="host")
    args = parser.parse_args()
    browser = runpy.run_path(str(ROOT / "scripts/run-browser-tests.py"))
    with ExitStack() as owners:
        stack = owners.enter_context(disposable_monitoring("host"))
        stack.up()
        environment = owners.enter_context(services(False))
        database = owners.enter_context(
            disposable_database(
                prefix="restaurantos_ssr_otel",
                test_url=environment["TEST_DATABASE_URL"],
            )
        )
        env = database.environment(environment)
        api_port, web_port = browser["free_port"](), browser["free_port"]()
        api, web = f"http://localhost:{api_port}", f"http://localhost:{web_port}"
        endpoint = f"http://127.0.0.1:{stack.port('collector', 4318)}"
        source_endpoint, source_exports = owners.enter_context(
            capture_exports(endpoint)
        )
        env.update(
            {
                "MONITORING_ENABLED": "true",
                "MONITORING_ENDPOINT": endpoint,
                "MONITORING_TRUSTED_UPSTREAM_IPS": '["127.0.0.1"]',
                "AUTH_TRUSTED_ORIGINS": json.dumps([web]),
                "PYTHONPATH": str(ROOT / "backend"),
                "API_URL": api,
                "NEXT_PUBLIC_API_URL": api,
                "M6_SOURCE_ROOT": str(ROOT),
            }
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            check=True,
        )
        accounts = []
        for _ in range(2):
            account = {
                "id": str(uuid4()),
                "email": f"ssr-{uuid4().hex}@example.test",
                "password": f"Synthetic SSR {uuid4().hex}",  # pragma: allowlist secret
            }
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "frontend/tests/seed-auth.py"),
                    "create",
                    account["id"],
                ],
                input=json.dumps(account),
                text=True,
                env=env,
                check=True,
                capture_output=True,
            )
            accounts.append(account)
        names = []
        processes = []
        log = owners.enter_context(
            open(stack.directory / "runtime.log", "w+", encoding="utf-8")
        )
        try:
            if args.mode == "host":
                frontend = owners.enter_context(browser["frontend_copy"]())
                subprocess.run(
                    [shutil.which("npm"), "run", "build"],
                    cwd=frontend,
                    env={**env, "MONITORING_ENABLED": "false"},
                    check=True,
                )
                processes.append(
                    subprocess.Popen(
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
                        cwd=stack.directory,
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                )

                def start_frontend():
                    processes.append(
                        subprocess.Popen(
                            [
                                shutil.which("node"),
                                str(frontend / "node_modules/next/dist/bin/next"),
                                "start",
                                "--hostname",
                                "localhost",
                                "--port",
                                str(web_port),
                            ],
                            cwd=frontend,
                            env={**env, "MONITORING_ENDPOINT": source_endpoint},
                            stdout=log,
                            stderr=log,
                        )
                    )

                def stop_frontend():
                    stop_processes(processes.pop())

                start_frontend()
            else:
                network = stack.project + "_monitoring"
                postgres = env["TEST_POSTGRES_CONTAINER"]
                command(
                    "docker",
                    "network",
                    "connect",
                    "--gw-priority",
                    "-1",
                    "--alias",
                    "postgres-otel",
                    network,
                    postgres,
                )
                owners.callback(
                    command, "docker", "network", "disconnect", network, postgres
                )
                frontend_name, api_name = (
                    stack.project + "-frontend",
                    stack.project + "-api",
                )
                names.extend([frontend_name, api_name])
                command(
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    frontend_name,
                    "--network",
                    network,
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "-p",
                    f"127.0.0.1:{web_port}:3000",
                    "-e",
                    "API_URL=http://ssr-api:8000",
                    "-e",
                    "MONITORING_ENABLED=true",
                    "-e",
                    "MONITORING_ENDPOINT=http://collector:4318",
                    "restaurantos-frontend:m9",
                )
                command(
                    "docker",
                    "network",
                    "connect",
                    stack.project + "_host_ingress",
                    frontend_name,
                )
                peer = json.loads(command("docker", "inspect", frontend_name))[0][
                    "NetworkSettings"
                ]["Networks"][network]["IPAddress"]
                api_env = {
                    **env,
                    "DATABASE_URL": make_url(database.async_url)
                    .set(host="postgres-otel", port=5432)
                    .render_as_string(hide_password=False),
                    "MONITORING_ENDPOINT": "http://collector:4318",
                    "MONITORING_TRUSTED_UPSTREAM_IPS": json.dumps([peer]),
                    "REDIS_URL": "redis://127.0.0.1:1/0",
                }
                env_file = stack.directory / "api.env"
                env_file.write_text(
                    "\n".join(
                        f"{key}={value}"
                        for key, value in api_env.items()
                        if key.startswith(("AUTH_", "MONITORING_"))
                        or key in {"DATABASE_URL", "REDIS_URL", "ENVIRONMENT"}
                    )
                )
                command(
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    api_name,
                    "--network",
                    network,
                    "--network-alias",
                    "ssr-api",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "-p",
                    f"127.0.0.1:{api_port}:8000",
                    "--env-file",
                    str(env_file),
                    "restaurantos-backend:m6",
                )
                command(
                    "docker",
                    "network",
                    "connect",
                    stack.project + "_host_ingress",
                    api_name,
                )

                def start_frontend():
                    command("docker", "start", frontend_name)

                def stop_frontend():
                    # Quiesce test clients; measure telemetry shutdown independently
                    # of Next's draining of persistent HTTP connections.
                    for client in clients:
                        client.close()
                    before = time.monotonic()
                    command("docker", "stop", "--time", "6", frontend_name)
                    elapsed = time.monotonic() - before
                    state = json.loads(command("docker", "inspect", frontend_name))[0][
                        "State"
                    ]
                    outcome = {
                        "seconds": round(elapsed, 3),
                        "exit_code": state["ExitCode"],
                        "oom": state["OOMKilled"],
                    }
                    print("Standalone stop:", json.dumps(outcome), flush=True)
                    assert elapsed < 7, outcome  # 6s container grace plus CLI overhead.
                    assert state["ExitCode"] in {0, 143} and not state["OOMKilled"], (
                        outcome
                    )

            try:
                wait_until(
                    lambda: requests.get(api + "/health", timeout=1).status_code == 200,
                    timeout=45,
                )
            except RuntimeError:
                if args.mode == "container":
                    output = subprocess.run(
                        ["docker", "logs", api_name],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    print(
                        browser["safe_diagnostics"](
                            output.stdout + output.stderr, api_env
                        )
                    )
                else:
                    log.flush()
                    print(
                        browser["safe_diagnostics"](
                            (stack.directory / "runtime.log").read_text(), env
                        )
                    )
                raise
            wait_until(
                lambda: requests.get(web + "/login", timeout=1).status_code == 200
            )
            clients = [requests.Session(), requests.Session()]
            csrf = {"Origin": web, "X-CSRF-Protection": "1"}
            for client, account in zip(clients, accounts, strict=True):
                assert (
                    request(
                        client,
                        "POST",
                        api + "/auth/login",
                        json={
                            "email": account["email"],
                            "password": account["password"],
                        },
                        headers=csrf,
                    ).status_code
                    == 200
                )
            canary = "SYNTHETIC-SSR-PRIVATE-" + uuid4().hex
            response = request(
                clients[0],
                "POST",
                api + "/api/restaurants",
                json={"name": canary, "address": "test", "phone": "123"},
                headers=csrf,
            )
            assert response.status_code == 201
            restaurant = response.json()["id"]
            response = request(
                clients[0],
                "POST",
                api + f"/restaurants/{restaurant}/menus",
                json={"name": canary},
                headers=csrf,
            )
            assert response.status_code in {200, 201}
            path = f"/restaurants/{restaurant}/menu"
            trace_id = uuid4().hex
            headers = {
                "traceparent": f"00-{trace_id}-1234567890abcdef-01",
                "baggage": "secret=" + canary,
                "tracestate": "vendor=" + canary,
                "Authorization": "Bearer " + canary,
                "X-Private": canary,
            }
            clients[0].cookies.set("private_canary", canary)
            response = request(
                clients[0], "GET", web + path + "?password=" + canary, headers=headers
            )
            assert response.status_code == 200 and canary in response.text
            assert "no-store" in response.headers["Cache-Control"]
            assert "Set-Cookie" not in response.headers
            stored = wait_until(lambda: correlation(stack, trace_id))
            assert canary not in json.dumps(stored)
            if args.mode == "host":
                assert trace_id in "".join(source_exports)
                assert canary not in "".join(source_exports)
            assert all(
                account["password"] not in json.dumps(stored) for account in accounts
            )
            for cookie in clients[0].cookies:
                assert cookie.value not in json.dumps(stored)
                if args.mode == "host":
                    assert cookie.value not in "".join(source_exports)
            for value in ("invalid," + canary, None):
                response = request(
                    clients[0],
                    "GET",
                    web + path,
                    headers={"traceparent": value} if value else {},
                )
                assert response.status_code == 200 and canary in response.text
            forbidden = request(clients[1], "GET", web + path)
            assert canary not in forbidden.text
            assert (
                request(
                    clients[1], "GET", api + f"/api/restaurants/{restaurant}"
                ).status_code
                == 404
            )
            error_trace = uuid4().hex
            request(
                clients[0],
                "GET",
                web
                + f"/restaurants/{restaurant}/menu/"
                + canary
                + "?private="
                + canary,
                headers={"traceparent": f"00-{error_trace}-1234567890abcdef-01"},
            )
            error_stored = wait_until(lambda: correlation(stack, error_trace))
            assert canary not in json.dumps(error_stored)
            assert any(
                span.get("status", {}).get("code") in (2, "STATUS_CODE_ERROR")
                for _, span in spans_in(error_stored)
            )
            body_trace = uuid4().hex
            request(
                clients[0],
                "POST",
                web + "/login?password=" + canary,
                data=canary,
                headers={
                    "Authorization": "Bearer " + canary,
                    "traceparent": f"00-{body_trace}-1234567890abcdef-01",
                },
            )
            body_stored = wait_until(
                lambda: stack.query("tempo", "/api/traces/" + body_trace)
            )
            assert spans_in(body_stored) and canary not in json.dumps(body_stored)
            if args.mode == "host":
                assert error_trace in "".join(source_exports)
                assert canary not in "".join(source_exports)
            # SSR expiry must redirect to browser renewal without rotating cookies or refresh.
            saved = clients[0].cookies.get("ros_access")
            clients[0].cookies.clear()
            expired = request(clients[0], "GET", web + path)
            assert expired.status_code in {307, 308} and expired.headers[
                "Location"
            ].startswith("/session/renew?")
            assert "Set-Cookie" not in expired.headers
            clients[0].cookies.set("ros_access", saved)
            # Cold startup while Collector is stopped, then identical authenticated/foreign rendering.
            stop_frontend()
            stack.compose("stop", "collector")
            start_frontend()
            wait_until(
                lambda: requests.get(web + "/login", timeout=1).status_code == 200
            )
            for _ in range(3):
                response = request(clients[0], "GET", web + path)
                assert (
                    response.status_code == 200
                    and canary in response.text
                    and "Set-Cookie" not in response.headers
                )
                assert canary not in request(clients[1], "GET", web + path).text
            stop_frontend()
            print(
                f"PASS: {args.mode} authenticated SSR distributed parentage in Tempo; invalid/missing parents; canary filtering; renewal redirect; tenant isolation; Collector-absent cold startup/requests/shutdown",
                flush=True,
            )
        finally:
            stop_processes(*processes)
            for name in names:
                command("docker", "rm", "--force", name)
    print(
        "PASS: owned monitoring, database, services and processes cleaned up",
        flush=True,
    )


if __name__ == "__main__":
    main()
