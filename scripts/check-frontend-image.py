"""Build and smoke-test the standalone frontend image without publishing it."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CONTENT_CHECK = r"""
const fs = require('node:fs');
for (const path of ['server.js', '.next/static', 'public/window.svg']) {
  if (!fs.existsSync('/app/' + path)) throw new Error('Missing runtime asset: ' + path);
}
for (const path of ['tests', 'coverage', 'node_modules/typescript', 'node_modules/eslint']) {
  if (fs.existsSync('/app/' + path)) throw new Error('Development content: ' + path);
}
function inspect(path) {
  for (const entry of fs.readdirSync(path, {withFileTypes: true})) {
    if (entry.name.startsWith('.env') || entry.name === '.npmrc' ||
        /\.(pem|key|p12|pfx)$/.test(entry.name)) throw new Error('Private file in runtime');
    if (entry.isDirectory()) inspect(path + '/' + entry.name);
  }
}
inspect('/app');
let prefixedClient = false;
function inspectBundles(path) {
  for (const entry of fs.readdirSync(path, {withFileTypes: true})) {
    const file = path + '/' + entry.name;
    if (entry.isDirectory()) inspectBundles(file);
    else if (entry.name.endsWith('.js') && fs.readFileSync(file, 'utf8').includes('/backend'))
      prefixedClient = true;
  }
}
inspectBundles('/app/.next/static');
if (!prefixedClient) throw new Error('Browser API prefix missing from bundles');
if (process.getuid() === 0) throw new Error('Runtime user is root');
console.log('Standalone assets, browser prefix and non-root runtime verified');
"""


def docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-6000:])
    return result


def inspect_image(image: str, platform: str | None) -> None:
    metadata = json.loads(docker("image", "inspect", image).stdout)[0]
    config = metadata["Config"]
    actual = f"{metadata['Os']}/{metadata['Architecture']}"
    if platform and actual != platform:
        raise RuntimeError(f"Expected {platform}, received {actual}")
    if config.get("User", "").split(":")[0] in {"", "0", "root"}:
        raise RuntimeError("Frontend must configure a non-root user")
    if config["Cmd"] != ["node", "server.js"]:
        raise RuntimeError("Frontend must start the standalone server")
    if not config.get("Healthcheck", {}).get("Test"):
        raise RuntimeError("Frontend must configure a healthcheck")
    for entry in config.get("Env", []):
        key = entry.partition("=")[0].upper()
        if key == "API_URL" or any(
            marker in key for marker in ("SECRET", "PASSWORD", "TOKEN", "DATABASE_URL")
        ):
            raise RuntimeError("Frontend image contains private runtime configuration")
    version = docker("run", "--rm", "--network", "none", image, "node", "--version")
    if not version.stdout.strip().startswith("v24."):
        raise RuntimeError("Frontend requires Node 24")
    docker("run", "--rm", "--network", "none", image, "node", "-e", CONTENT_CHECK)
    print(f"Frontend {metadata['Id']}: {actual}, {metadata['Size']} bytes", flush=True)


def fetch(port: int, path: str) -> bytes:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
        if response.status != 200:
            raise RuntimeError("Unexpected frontend response status")
        return response.read()


def smoke(image: str, timeout: float, inject_failure: bool) -> None:
    name = "restaurantos-frontend-image-" + uuid4().hex[:12]
    try:
        docker(
            "run",
            "--detach",
            "--name",
            name,
            "--publish",
            "127.0.0.1::3000",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=512m",
            "--pids-limit=128",
            "--env",
            "API_URL=http://127.0.0.1:1",
            image,
        )
        port = int(docker("port", name, "3000/tcp").stdout.strip().rsplit(":", 1)[1])
        deadline = time.monotonic() + timeout
        while True:
            try:
                html = fetch(port, "/").decode()
                break
            except (OSError, TimeoutError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Frontend did not become ready") from None
                state = docker(
                    "inspect", "--format", "{{.State.Status}}", name
                ).stdout.strip()
                if state != "running":
                    raise RuntimeError("Frontend stopped before readiness")
                time.sleep(0.5)
        if "Your restaurant workspace" not in html:
            raise RuntimeError("Standalone homepage did not render")
        if b"Sign in" not in fetch(port, "/login"):
            raise RuntimeError("Standalone login page did not render")
        if b"<svg" not in fetch(port, "/window.svg"):
            raise RuntimeError("Public assets were not served")
        assets = set(
            re.findall(r'(?:src|href)="([^"<>]*?/_next/static/[^"<>]+)"', html)
        )
        if not assets:
            raise RuntimeError("Homepage has no static assets to verify")
        for path in assets:
            if not path.startswith("/_next/static/"):
                raise RuntimeError("Unexpected static asset origin")
            fetch(port, path.replace("&amp;", "&"))
        # Run the exact image health command too; homepage startup alone does not
        # prove that Docker's configured healthcheck can execute as this user.
        docker(
            "exec",
            name,
            "node",
            "-e",
            "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
        )
        if inject_failure:
            raise RuntimeError("Intentional failure after frontend smoke")
        print(
            "PASS: standalone pages, public/static assets and healthcheck", flush=True
        )
    finally:
        docker("rm", "--force", name, check=False)
        if docker("ps", "-aq", "--filter", f"name=^/{name}$").stdout.strip():
            raise RuntimeError("Frontend smoke container cleanup failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="restaurantos-frontend:m9")
    parser.add_argument("--platform", choices=("linux/amd64", "linux/arm64"))
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--inject-failure-after", choices=("healthy",))
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        docker("info")
        platform = ["--platform", args.platform] if args.platform else []
        print(f"Building standalone frontend image {args.image}", flush=True)
        docker(
            "build",
            "--pull",
            *platform,
            "--tag",
            args.image,
            "--file",
            str(ROOT / "frontend/Dockerfile"),
            str(ROOT / "frontend"),
        )
        inspect_image(args.image, args.platform)
        smoke(args.image, args.timeout, bool(args.inject_failure_after))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"FAIL: frontend image check: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
