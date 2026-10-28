#!/bin/bash
# Disposable, unprivileged Docker regression only. Never run on an OCI host.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[[ -f /.dockerenv && $EUID == 0 && $# == 0 && ! -e /etc/restaurantos ]]
for file in /bundle/*.cloud-config.yaml; do
    cloud-init schema --config-file "$file"
done
for file in /templates/*.sh; do
    bash -n "$file"
    shellcheck --severity=warning "$file"
done
# A rejected invocation must have no configuration/account/package side effects.
if bash /templates/harden-ssh.sh; then exit 1; fi
if bash /templates/install-docker.sh --unexpected; then exit 1; fi
[[ ! -e /etc/ssh/sshd_config.d/00-restaurantos.conf && ! -e /etc/docker/daemon.json ]]
for module in bootcmd users_groups write_files; do
    cloud-init single --file /bundle/testing.cloud-config.yaml --name "$module" --frequency always
done
[[ $(stat -c '%U:%G:%a' /etc/restaurantos) == root:root:700 ]]
[[ $(stat -c '%U:%G:%a' /opt/restaurantos/bootstrap/harden-ssh.sh) == root:root:600 ]]
[[ $(cat /etc/restaurantos/environment) == testing ]]
[[ $(id -nG ros-deploy) == ros-deploy ]]
[[ $(getent passwd ros-deploy) == *:/usr/sbin/nologin ]]
[[ ! -s /home/ros-deploy/.ssh/authorized_keys ]]
policy=$(LC_ALL=C sudo -n -l -U ros-deploy 2>&1) || true
grep -q '^User ros-deploy is not allowed to run sudo on ' <<<"$policy"
if runuser -u ros-deploy -- sudo -n /usr/bin/true; then exit 1; fi
sudo -n -l -U rosadmin >/dev/null
mkdir -p /run/sshd
ssh-keygen -A >/dev/null
# This container has no systemd PID 1. Hardening must parse successfully but the
# real service reload must fail; no simulated reload is counted as host proof.
if bash /opt/restaurantos/bootstrap/harden-ssh.sh rosadmin --second-session-and-console-verified; then
    echo 'Unexpected systemd reload in the container' >&2
    exit 1
fi
sshd -t
effective=$(sshd -T)
grep -qx 'allowusers rosadmin' <<<"$effective"
grep -qx 'passwordauthentication no' <<<"$effective"
grep -qx 'permitrootlogin no' <<<"$effective"
if bash /opt/restaurantos/bootstrap/harden-ssh.sh rosadmin --second-session-and-console-verified; then
    echo 'Hardening unexpectedly replaced its existing file' >&2
    exit 1
fi
# Missing Docker/systemd/rules must make the local audit fail closed.
if bash /opt/restaurantos/bootstrap/audit-host.sh rosadmin >/tmp/audit.log; then
    echo 'Incomplete host unexpectedly passed audit' >&2
    exit 1
fi
grep -qx 'FAIL docker_active' /tmp/audit.log
grep -qx 'FAIL metadata_rule_presence' /tmp/audit.log
grep -qx 'PASS deployment_disabled' /tmp/audit.log
# A future accidental sudo grant must change the deployment-identity result.
printf 'ros-deploy ALL=(ALL) NOPASSWD: /usr/bin/true\n' >/etc/sudoers.d/99-bootstrap-regression
chmod 0440 /etc/sudoers.d/99-bootstrap-regression
if bash /opt/restaurantos/bootstrap/audit-host.sh rosadmin >/tmp/granted-audit.log; then exit 1; fi
grep -qx 'FAIL deployment_disabled' /tmp/granted-audit.log
rm /etc/sudoers.d/99-bootstrap-regression
echo 'PASS: schema, shell analysis, real cloud-init modules, SSH policy and fail-closed audit'
echo 'BOUNDARY: no OCI boot, network privileges, systemd reload/reboot or Docker installation tested'
