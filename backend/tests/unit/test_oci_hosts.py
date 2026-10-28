"""Unsafe provisioning inputs fail before any review bundle is written."""

import base64
import copy
import importlib.util
import json
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TODAY = datetime.now(UTC).date()


@pytest.fixture
def helper():
    spec = importlib.util.spec_from_file_location(
        "oci_hosts", ROOT / "scripts/prepare-oci-hosts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inventory():
    value = json.loads((ROOT / "deploy/oci/inventory.example.json").read_text())
    # Synthetic valid wire-format key: no usable private key exists.
    key = (
        "ssh-ed25519 "
        + base64.b64encode(
            struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + b"x" * 32
        ).decode()
    )
    value["home_region"] = "ap-singapore-1"
    value["eligibility_review"].update(date=TODAY.isoformat(), console_verified=True)
    for host in value["hosts"].values():
        host.update(
            image_id="ocid1.image.oc1.ap-singapore-1.synthetic",
            admin_public_key=key,
            admin_ipv4_cidr="8.8.8.8/32",
        )
    return value


@pytest.mark.parametrize(
    "field,value",
    [
        ("console_verified", False),
        ("console_verified", "true"),
        ("date", (TODAY - timedelta(days=2)).isoformat()),
        ("date", (TODAY + timedelta(days=1)).isoformat()),
        ("existing_ocpus", 1),
        ("existing_memory_gb", 1),
        ("existing_storage_gb", 101),
        ("existing_storage_gb", -1),
        ("existing_ocpus", True),
    ],
)
def test_no_unreviewed_or_over_budget_bundle(helper, inventory, tmp_path, field, value):
    inventory["eligibility_review"][field] = value
    output = tmp_path / "bundle"
    with pytest.raises(ValueError):
        helper.render(inventory, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("admin_ipv4_cidr", "0.0.0.0/0"),
        ("admin_ipv4_cidr", "8.8.8.0/24"),
        ("admin_ipv4_cidr", "127.0.0.1/32"),
        ("admin_ipv4_cidr", "::/0"),
        ("admin_ipv4_cidr", "10.0.0.1/32"),
        ("vcn_cidr", "0.0.0.0/0"),
        ("vcn_cidr", "169.254.0.0/16"),
        ("hostname", "$(touch /tmp/injected)"),
        ("shape", "VM.Standard.E4.Flex"),
        ("ocpus", True),
        ("ocpus", 2),
        ("memory_gb", 12),
        ("boot_gb", 200),
        ("image_id", "ocid1.image.oc1.eu-frankfurt-1.synthetic"),
        (
            "admin_public_key",
            "-----BEGIN OPENSSH PRIVATE KEY-----",  # pragma: allowlist secret
        ),
        ("admin_public_key", 'command="/bin/bash" ssh-ed25519 eA=='),
        ("admin_public_key", "ssh-ed25519 eA=="),
        ("admin_public_key", "ssh-ed25519 !!!"),
        ("admin_public_key", "ssh-ed25519 eA==\nssh-ed25519 eA=="),
    ],
)
def test_reject_unsafe_host_fields(helper, inventory, field, value):
    inventory["hosts"]["application"][field] = value
    with pytest.raises(ValueError):
        helper.validate(inventory)


def test_isolation_and_unknown_fields(helper, inventory):
    overlap = copy.deepcopy(inventory)
    overlap["hosts"]["testing"]["vcn_cidr"] = "10.60.1.0/24"
    with pytest.raises(ValueError, match="overlap"):
        helper.validate(overlap)
    inventory["hosts"]["application"]["private_key"] = (
        "must never be accepted"  # pragma: allowlist secret
    )
    with pytest.raises(ValueError, match="unknown"):
        helper.validate(inventory)


@pytest.mark.parametrize(
    "admin",
    ["root", "ubuntu", "rosdeploy", "daemon", "../root", "admin;id", "admin\nroot"],
)
def test_reject_unsafe_admin(helper, inventory, admin):
    inventory["admin_user"] = admin
    with pytest.raises(ValueError):
        helper.validate(inventory)


def test_bundle_is_inert_private_and_cannot_overwrite(helper, inventory, tmp_path):
    output = tmp_path / "review"
    hashes = helper.render(inventory, output)
    for environment in ("application", "testing"):
        path = output / f"{environment}.cloud-config.yaml"
        assert path.name in hashes
        config = json.loads(path.read_text().split("\n", 1)[1])
        assert "runcmd" not in config
        assert config["ssh_pwauth"] is False
        deploy = next(
            u
            for u in config["users"]
            if isinstance(u, dict) and u["name"] == "ros-deploy"
        )
        assert deploy["shell"] == "/usr/sbin/nologin"
        assert deploy["lock_passwd"] is True
        assert "ssh_authorized_keys" not in deploy
        assert "sudo" not in deploy
        assert "groups" not in deploy
        assert all(
            f["owner"] == "root:root" and f["permissions"] == "0600"
            for f in config["write_files"]
        )
        assert all(
            cmd[:9]
            == ["install", "-d", "-o", "root", "-g", "root", "-m", "0700", cmd[8]]
            for cmd in config["bootcmd"]
        )
        marker = next(
            f
            for f in config["write_files"]
            if f["path"] == "/etc/restaurantos/environment"
        )
        assert marker["content"] == environment + "\n"
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(FileExistsError):
        helper.render(inventory, output)
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}


def test_example_deliberately_cannot_provision(helper):
    example = json.loads((ROOT / "deploy/oci/inventory.example.json").read_text())
    with pytest.raises(ValueError):
        helper.validate(example)


@pytest.mark.parametrize(
    "region,ocid_region", [("us-phoenix-1", "phx"), ("us-ashburn-1", "iad")]
)
def test_legacy_ocid_region_names(helper, inventory, region, ocid_region):
    inventory["home_region"] = region
    for host in inventory["hosts"].values():
        host["image_id"] = f"ocid1.image.oc1.{ocid_region}.synthetic"
    helper.validate(inventory)
    inventory["hosts"]["testing"]["image_id"] = (
        "ocid1.image.oc1.ap-singapore-1.synthetic"
    )
    with pytest.raises(ValueError, match="home region"):
        helper.validate(inventory)
