#!/bin/bash
# Read-only local observations. Emit labels only, never keys, IPs or daemon env.
set -uo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
if [[ $EUID != 0 || $# != 1 || ! $1 =~ ^[a-z][a-z0-9]{2,23}$ ]]; then
    echo 'Usage: sudo bash audit-host.sh ADMIN' >&2
    exit 1
fi
admin=$1
failed=0
check() {
    local label=$1
    shift
    if "$@" >/dev/null 2>&1; then
        printf 'PASS %s\n' "$label"
    else
        printf 'FAIL %s\n' "$label"
        failed=1
    fi
}
is_arm() { [[ $(uname -m) == aarch64 ]]; }
is_ubuntu() { grep -qx 'ID=ubuntu' /etc/os-release && grep -qx 'VERSION_ID="24.04"' /etc/os-release; }
private_root_dir() { [[ $(stat -c '%U:%G:%a' "$1") == root:root:700 && ! -L $1 ]]; }
deploy_is_inert() {
    local entry groups
    entry=$(getent passwd ros-deploy) || return 1
    [[ ${entry##*:} == /usr/sbin/nologin ]] || return 1
    groups=$(id -nG ros-deploy) || return 1
    [[ $groups == ros-deploy ]] || return 1
    [[ ! -s /home/ros-deploy/.ssh/authorized_keys ]] || return 1
    ! runuser -u ros-deploy -- test -r /var/run/docker.sock || return 1
    # Some sudo versions return zero for a successful policy query that reports
    # no privileges. Inspect its C-locale denial rather than the exit code alone.
    local policy
    policy=$(LC_ALL=C sudo -n -l -U ros-deploy 2>&1) || true
    grep -q '^User ros-deploy is not allowed to run sudo on ' <<<"$policy"
}
ssh_effective() {
    local config
    config=$(sshd -T) || return 1
    for expected in 'permitrootlogin no' 'passwordauthentication no' 'kbdinteractiveauthentication no' 'authenticationmethods publickey' 'allowtcpforwarding no' 'allowagentforwarding no' "allowusers $admin"; do
        grep -qx "$expected" <<<"$config" || return 1
    done
}
no_other_public_listeners() {
    local address port listeners
    listeners=$(ss -H -lnt) || return 1
    while read -r address; do
        port=${address##*:}
        [[ $address == 127.* || $address == '[::1]:'* ]] && continue
        [[ $port == 22 || $port == 80 || $port == 443 ]] || return 1
    done < <(awk '{print $4}' <<<"$listeners")
}
metadata_rules() {
    iptables -w -C DOCKER-USER -j ROS-METADATA || return 1
    for interface in docker0 'br-+'; do
        iptables -w -C ROS-METADATA -i "$interface" -d 169.254.0.0/16 -j DROP || return 1
        ip6tables -w -C FORWARD -i "$interface" -d fe80::/10 -j DROP || return 1
    done
}
bounded_logs() { [[ $(docker info --format '{{.LoggingDriver}}') == json-file ]]; }
docker_version() {
    local version
    version=$(docker version --format '{{.Server.Version}}') || return 1
    [[ ${version%%.*} =~ ^[0-9]+$ ]] && (( ${version%%.*} >= 28 ))
}
daemon_policy() {
    python3 -c 'import json; from pathlib import Path; c=json.loads(Path("/etc/docker/daemon.json").read_text()); assert c.get("log-driver")=="json-file" and c.get("log-opts")=={"max-size":"10m","max-file":"3"} and c.get("live-restore") is False and c.get("ipv6") is False'
}
check architecture is_arm
check operating_system is_ubuntu
check admin_account id "$admin"
check ssh_syntax sshd -t
check ssh_policy ssh_effective
check deployment_disabled deploy_is_inert
for directory in /etc/restaurantos /opt/restaurantos /opt/restaurantos/bootstrap /opt/restaurantos/releases /var/lib/restaurantos; do
    check "private_directory:$directory" private_root_dir "$directory"
done
check docker_enabled systemctl is-enabled --quiet docker.service
check docker_active systemctl is-active --quiet docker.service
check docker_version docker_version
check compose_plugin docker compose version
check daemon_policy daemon_policy
check bounded_default_logging bounded_logs
check metadata_rule_presence metadata_rules
check guard_enabled systemctl is-enabled --quiet restaurantos-network-guard.service
check guard_active systemctl is-active --quiet restaurantos-network-guard.service
check public_listener_allowlist no_other_public_listeners
printf 'BOUNDARY local observations only; OCI/external/reboot/live-denial proof required\n'
exit "$failed"
