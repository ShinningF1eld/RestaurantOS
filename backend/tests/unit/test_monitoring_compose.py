"""Guard monitoring isolation and its declared budget without Docker/services."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
MONITORING = ROOT / "monitoring"


def load_compose(name):
    return yaml.safe_load((MONITORING / name).read_text(encoding="utf-8"))


def test_monitoring_images_and_combined_hard_budget_match_lock():
    compose = load_compose("compose.yaml")
    lock = json.loads((MONITORING / "images.lock.json").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == set(lock["images"])
    assert (
        sum(s["mem_limit"] for s in services.values())
        <= lock["monitoring_memory_budget_bytes"]
    )
    for name, service in services.items():
        assert service["image"] == lock["images"][name]["reference"]
        assert isinstance(service["mem_limit"], int) and service["mem_limit"] > 0
        # Equal memory+swap and memory limits prevent an extra swap allowance.
        assert service["memswap_limit"] == service["mem_limit"]
        assert "build" not in service


def test_base_has_no_host_ports_or_shared_application_resources():
    compose = load_compose("compose.yaml")
    assert compose["networks"]["monitoring"]["internal"] is True
    for network in compose["networks"].values():
        assert not network.get("external") and "name" not in network
    for volume in compose["volumes"].values():
        assert not volume.get("external") and "name" not in volume
    for service in compose["services"].values():
        assert not service.get("ports")
        assert service["networks"] == ["monitoring"]
        assert "network_mode" not in service and "container_name" not in service
        assert not service.get("privileged")
        assert service["read_only"] is True
        assert "ALL" in service["cap_drop"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["logging"]["driver"] == "json-file"
        assert service["logging"]["options"]["max-size"]
        assert service["logging"]["options"]["max-file"]


def test_host_override_only_publishes_loopback_ui_and_http_ingress():
    overlay = load_compose("compose.host.yaml")
    assert set(overlay) == {"services", "networks"}
    assert set(overlay["networks"]) == {"host_ingress"}
    assert "name" not in overlay["networks"]["host_ingress"]
    assert not overlay["networks"]["host_ingress"].get("external")
    assert set(overlay["services"]) == {"grafana", "collector"}
    targets = {"grafana": 3000, "collector": 4318}
    for name, service in overlay["services"].items():
        assert set(service) == {"ports", "networks"}
        assert service["networks"] == ["monitoring", "host_ingress"]
        assert len(service["ports"]) == 1
        port = service["ports"][0]
        assert port["host_ip"] == "127.0.0.1"
        assert port["protocol"] == "tcp"
        assert port["target"] == targets[name]
        assert ":-3000}" not in port["published"]


def test_writable_storage_is_project_owned_and_configuration_fails_closed():
    compose = load_compose("compose.yaml")
    persistent = set()
    for service in compose["services"].values():
        for mount in service.get("volumes", []):
            if isinstance(mount, str):
                source, _, target = mount.partition(":")
                assert source in compose["volumes"]
                assert target.startswith("/")
                persistent.add(source)
            else:
                assert mount["type"] == "bind"
                assert mount["read_only"] is True
                assert mount["bind"]["create_host_path"] is False
                assert mount["source"].startswith("./")
                assert "docker.sock" not in mount["source"]
    assert persistent == set(compose["volumes"])
    grafana = compose["services"]["grafana"]
    environment = grafana["environment"]
    assert environment["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert environment["GF_USERS_ALLOW_SIGN_UP"] == "false"
    assert "GF_SECURITY_ADMIN_PASSWORD" not in environment
    for secret in ("grafana_admin_user", "grafana_admin_password"):
        assert secret in grafana["secrets"]
        setting = secret.removeprefix("grafana_").upper()
        assert environment[f"GF_SECURITY_{setting}__FILE"] == (f"/run/secrets/{secret}")
        assert compose["secrets"][secret]["file"].startswith("${MONITORING_STATE_DIR:?")
    assert "/.local-monitoring/" in (ROOT / ".gitignore").read_text()
