#!/bin/bash
# Run through the trusted admin path, only after a second session and console work.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
if [[ $EUID != 0 || $# != 2 || $2 != --second-session-and-console-verified || ! $1 =~ ^[a-z][a-z0-9]{2,23}$ ]]; then
    echo 'Usage: sudo bash harden-ssh.sh ADMIN --second-session-and-console-verified' >&2
    exit 1
fi
admin=$1
[[ $admin != root && $admin != ubuntu && $admin != rosdeploy ]]
id "$admin" >/dev/null
id -nG "$admin" | tr ' ' '\n' | grep -qx sudo
[[ -s /home/$admin/.ssh/authorized_keys ]]
[[ -f /etc/restaurantos/environment ]]
config=/etc/ssh/sshd_config.d/00-restaurantos.conf
[[ ! -e $config ]] || { echo 'Existing hardening file: review manually; refusing replacement.' >&2; exit 1; }
umask 077
candidate=$(mktemp /etc/ssh/sshd_config.d/.restaurantos.XXXXXXXX)
trap 'rm -f -- "$candidate"' EXIT
cat >"$candidate" <<EOF
# Installed after named-admin second-session and OCI recovery verification.
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthenticationMethods publickey
AllowUsers $admin
AllowAgentForwarding no
AllowTcpForwarding no
X11Forwarding no
PermitTunnel no
PermitUserEnvironment no
EOF
# Publish complete bytes atomically and refuse a competing/existing target.
ln -- "$candidate" "$config"
# sshd's first value wins. Verify the effective result, not just this file.
valid=true
effective=$(sshd -T) || valid=false
sshd -t || valid=false
for expected in 'permitrootlogin no' 'passwordauthentication no' 'kbdinteractiveauthentication no' 'pubkeyauthentication yes' 'authenticationmethods publickey' "allowusers $admin" 'allowagentforwarding no' 'allowtcpforwarding no' 'x11forwarding no' 'permittunnel no' 'permituserenvironment no'; do
    grep -qx "$expected" <<<"$effective" || valid=false
done
if [[ $valid != true ]]; then
    rm -- "$config"
    echo 'Effective SSH configuration rejected; service was not reloaded.' >&2
    exit 1
fi
systemctl reload ssh.service
echo 'SSH reloaded. Keep this session; prove a fresh admin login before closing it.'
