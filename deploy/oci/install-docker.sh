#!/bin/bash
# Fresh Ubuntu 24.04 ARM host only. Trusted administrator invokes explicitly.
# Uses Docker's signed apt repository; never curl-pipe a remote installer.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[[ $EUID == 0 && $# == 0 && $(uname -m) == aarch64 ]]
grep -qx 'ID=ubuntu' /etc/os-release
grep -qx 'VERSION_ID="24.04"' /etc/os-release
grep -Eq '^(application|testing)$' /etc/restaurantos/environment
if command -v docker >/dev/null || [[ -e /etc/docker/daemon.json || -e /etc/apt/sources.list.d/docker.sources ]]; then
    echo 'Existing Docker/configuration found; inspect instead of overwriting.' >&2
    exit 1
fi
# Stop on conflicting distro packages; removing an unknown runtime is not safe.
for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc; do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
        echo 'Conflicting runtime package found; inspect manually.' >&2
        exit 1
    fi
done
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl iptables sudo python3
install -d -m 0755 /etc/apt/keyrings
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc
cat >/etc/apt/sources.list.d/docker.sources <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: arm64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
install -d -m 0755 /etc/docker
install -o root -g root -m 0644 /opt/restaurantos/bootstrap/daemon.json /etc/docker/daemon.json
apt-get update
apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker.service
install -o root -g root -m 0644 /opt/restaurantos/bootstrap/restaurantos-network-guard.service /etc/systemd/system/restaurantos-network-guard.service
systemctl daemon-reload
systemctl enable --now restaurantos-network-guard.service
umask 077
dpkg-query -W -f='${Package} ${Version}\n' docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/var/lib/restaurantos/host-packages.txt
echo 'Docker installed; retain package inventory and run local/live/reboot checks before applications.'
