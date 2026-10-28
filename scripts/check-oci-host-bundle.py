"""Run synthetic bootstrap regressions in an isolated Ubuntu toolchain container."""

import argparse
import base64
import importlib.util
import json
import re
import struct
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="restaurantos-oci-validation:local")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9./:@_-]*", args.image):
        parser.error("Expected a local validation image reference")
    spec = importlib.util.spec_from_file_location(
        "oci_hosts", ROOT / "scripts/prepare-oci-hosts.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    inventory = json.loads((ROOT / "deploy/oci/inventory.example.json").read_text())
    inventory["home_region"] = "ap-singapore-1"
    inventory["eligibility_review"].update(
        date=datetime.now(UTC).date().isoformat(), console_verified=True
    )
    # Synthetic structural fixture only: no tenancy verification or private key.
    key = (
        "ssh-ed25519 "
        + base64.b64encode(
            struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + b"x" * 32
        ).decode()
    )
    for host in inventory["hosts"].values():
        host.update(
            image_id="ocid1.image.oc1.ap-singapore-1.synthetic",
            admin_public_key=key,
            admin_ipv4_cidr="8.8.8.8/32",
        )
    with tempfile.TemporaryDirectory(prefix="restaurantos-oci-test-") as directory:
        bundle = Path(directory) / "bundle"
        helper.render(inventory, bundle)
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--mount",
                f"type=bind,source={bundle},target=/bundle,readonly",
                "--mount",
                f"type=bind,source={ROOT / 'deploy/oci'},target=/templates,readonly",
                "--entrypoint",
                "bash",
                args.image,
                "/templates/check-bootstrap.sh",
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
