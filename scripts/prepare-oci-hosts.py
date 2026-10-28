"""Validate an operator inventory and render inert S2 cloud-init review bundles.

No OCI API, SSH, provisioning, package installation or host mutation occurs here.
Generated user-data creates accounts/directories; host controls are staged only.
"""

import argparse
import base64
import binascii
import hashlib
import ipaddress
import json
import re
import struct
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "deploy/oci"


def exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label}: missing or unknown fields")


def public_key(value):
    """Accept only plain Ed25519 keys, never authorized_keys options or secrets."""
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        raise ValueError("Expected a single-line Ed25519 public key")
    parts = value.split()
    if len(parts) != 2 or parts[0] != "ssh-ed25519":
        raise ValueError("Use an Ed25519 public key without options or comment")
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid public key encoding") from error
    expected = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32)
    if len(blob) != len(expected) + 32 or not blob.startswith(expected):
        raise ValueError("Invalid Ed25519 public key wire format")
    return "ssh-ed25519 " + base64.b64encode(blob).decode("ascii")


def validate(inventory):
    exact_keys(
        inventory,
        ["version", "home_region", "eligibility_review", "admin_user", "hosts"],
        "inventory",
    )
    if type(inventory["version"]) is not int or inventory["version"] != 1:
        raise ValueError("Unsupported inventory version")
    region = inventory["home_region"]
    if not isinstance(region, str) or not re.fullmatch(r"[a-z]+-[a-z]+-\d+", region):
        raise ValueError("Set the actual OCI home region")
    review = inventory["eligibility_review"]
    exact_keys(
        review,
        [
            "date",
            "console_verified",
            "existing_ocpus",
            "existing_memory_gb",
            "existing_storage_gb",
        ],
        "eligibility review",
    )
    try:
        reviewed = date.fromisoformat(review["date"])
    except (TypeError, ValueError) as error:
        raise ValueError("Record the console review date as YYYY-MM-DD") from error
    age = (datetime.now(UTC).date() - reviewed).days
    if age < 0 or age > 1 or review["console_verified"] is not True:
        raise ValueError("A current console eligibility review is required")
    for field in ("existing_ocpus", "existing_memory_gb", "existing_storage_gb"):
        if type(review[field]) is not int or review[field] < 0:
            raise ValueError("Existing resource totals must be nonnegative integers")
    if (
        review["existing_ocpus"] + 2 > 2
        or review["existing_memory_gb"] + 12 > 12
        or review["existing_storage_gb"] + 100 > 200
    ):
        raise ValueError("Proposed hosts exceed the reviewed free-resource budget")
    admin = inventory["admin_user"]
    if (
        not isinstance(admin, str)
        or not re.fullmatch(r"[a-z][a-z0-9]{2,23}", admin)
        or admin in {"root", "ubuntu", "rosdeploy", "daemon", "nobody"}
    ):
        raise ValueError("Choose a dedicated named administrator")
    hosts = inventory["hosts"]
    exact_keys(hosts, ["application", "testing"], "hosts")
    for environment, host in hosts.items():
        exact_keys(
            host,
            [
                "hostname",
                "shape",
                "ocpus",
                "memory_gb",
                "boot_gb",
                "image_id",
                "admin_public_key",
                "admin_ipv4_cidr",
                "vcn_cidr",
            ],
            environment,
        )
        if host["hostname"] != f"restaurantos-{environment}":
            raise ValueError("Use environment-specific hostnames")
        if (
            host["shape"] != "VM.Standard.A1.Flex"
            or type(host["ocpus"]) is not int
            or host["ocpus"] != 1
            or type(host["memory_gb"]) is not int
            or host["memory_gb"] != (8 if environment == "application" else 4)
            or type(host["boot_gb"]) is not int
            or host["boot_gb"] != 50
        ):
            raise ValueError("Host sizing differs from the accepted two-host split")
        if (
            not isinstance(host["image_id"], str)
            or not re.fullmatch(
                r"ocid1\.image\.oc1\.[a-z0-9-]+\.[a-z0-9]+", host["image_id"]
            )
            or host["image_id"].split(".")[3] != region
        ):
            raise ValueError(
                "Record an eligible Ubuntu 24.04 ARM image in the home region"
            )
        public_key(host["admin_public_key"])
        if not isinstance(host["admin_ipv4_cidr"], str) or not isinstance(
            host["vcn_cidr"], str
        ):
            raise TypeError("Network fields must be explicit CIDR strings")
        source = ipaddress.ip_network(host["admin_ipv4_cidr"], strict=True)
        if (
            source.version != 4
            or source.prefixlen != 32
            or not source.network_address.is_global
        ):
            raise ValueError("SSH ingress must name one public administrator IPv4 /32")
        vcn = ipaddress.ip_network(host["vcn_cidr"], strict=True)
        private = ipaddress.ip_network("10.0.0.0/8")
        if (
            vcn.version != 4
            or not vcn.subnet_of(private)
            or not 16 <= vcn.prefixlen <= 24
        ):
            raise ValueError("Use an explicit private 10/8 VCN with /16 through /24")
    if ipaddress.ip_network(hosts["application"]["vcn_cidr"]).overlaps(
        ipaddress.ip_network(hosts["testing"]["vcn_cidr"])
    ):
        raise ValueError("Application and testing VCN ranges must not overlap")
    return inventory


def cloud_config(inventory, environment):
    host = inventory["hosts"][environment]
    files = []
    for name in (
        "harden-ssh.sh",
        "install-docker.sh",
        "docker-network-guard.sh",
        "restaurantos-network-guard.service",
        "audit-host.sh",
        "daemon.json",
    ):
        files.append(
            {
                "path": f"/opt/restaurantos/bootstrap/{name}",
                "owner": "root:root",
                "permissions": "0600",
                "content": (TEMPLATES / name).read_text(encoding="utf-8"),
            }
        )
    return {
        "hostname": host["hostname"],
        "ssh_pwauth": False,
        "disable_root": True,
        "users": [
            "default",
            {
                "name": inventory["admin_user"],
                "groups": ["sudo"],
                "sudo": ["ALL=(ALL) NOPASSWD:ALL"],
                "shell": "/bin/bash",
                "lock_passwd": True,
                "ssh_authorized_keys": [public_key(host["admin_public_key"])],
            },
            {"name": "ros-deploy", "shell": "/usr/sbin/nologin", "lock_passwd": True},
        ],
        "bootcmd": [
            ["install", "-d", "-o", "root", "-g", "root", "-m", "0700", path]
            for path in (
                "/etc/restaurantos",
                "/opt/restaurantos",
                "/opt/restaurantos/bootstrap",
                "/opt/restaurantos/releases",
                "/var/lib/restaurantos",
            )
        ],
        "write_files": files
        + [
            {
                "path": "/etc/restaurantos/environment",
                "owner": "root:root",
                "permissions": "0600",
                "content": environment + "\n",
            }
        ],
        # No runcmd: scripts are reviewed/run only after second-session proof.
    }


def render(inventory, output):
    validate(inventory)
    output = Path(output)
    # mkdir without exist_ok prevents replacement of an existing review bundle.
    output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for environment in ("application", "testing"):
        content = (
            "#cloud-config\n"
            + json.dumps(cloud_config(inventory, environment), indent=2)
            + "\n"
        )
        path = output / f"{environment}.cloud-config.yaml"
        path.write_text(content, encoding="utf-8", newline="\n")
        hashes[path.name] = hashlib.sha256(content.encode()).hexdigest()
    plan = {
        "boundary": "Review plan only; no OCI resources or firewall rules applied",
        "public_ipv6": False,
        "hosts": {
            name: {
                "vcn_cidr": host["vcn_cidr"],
                "ingress": [
                    {"protocol": "tcp", "port": 22, "source": host["admin_ipv4_cidr"]}
                ],
                "public_application_ingress": "deferred to S3",
                "cross_environment_routes": False,
                "ci_ssh_ingress": "disabled until S5 review",
            }
            for name, host in inventory["hosts"].items()
        },
    }
    content = json.dumps(plan, indent=2) + "\n"
    (output / "network-plan.json").write_text(content, encoding="utf-8", newline="\n")
    hashes["network-plan.json"] = hashlib.sha256(content.encode()).hexdigest()
    (output / "sha256.json").write_text(
        json.dumps(hashes, indent=2) + "\n", encoding="utf-8"
    )
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument(
        "--output", type=Path, help="Create a NEW directory with inert review files"
    )
    args = parser.parse_args()
    try:
        inventory = validate(json.loads(args.inventory.read_text(encoding="utf-8")))
        if args.output:
            render(inventory, args.output)
        print(
            "PASS: inventory policy (not OCI eligibility, provisioning or live security)"
        )
    except (ValueError, TypeError, OSError) as error:
        # Do not echo an input value: an accidental secret may be malformed input.
        parser.exit(
            1,
            f"Inventory/bundle rejected: {type(error).__name__}; check the runbook and input fields.\n",
        )


if __name__ == "__main__":
    main()
