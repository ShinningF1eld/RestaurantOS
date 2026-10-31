#!/bin/bash
# Additive rules only; never flush OCI/Ubuntu/Docker-managed chains.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[[ $EUID == 0 && $# == 0 ]]
iptables -w -nL DOCKER-USER >/dev/null
if ! iptables -w -nL ROS-METADATA >/dev/null 2>&1; then
    iptables -w -N ROS-METADATA
fi
# Include the default bridge and Compose-generated bridges. Host networking,
# macvlan/ipvlan and custom bridge names are forbidden by the host runbook.
for interface in docker0 'br-+'; do
    if ! iptables -w -C ROS-METADATA -i "$interface" -d 169.254.0.0/16 -j DROP 2>/dev/null; then
        iptables -w -A ROS-METADATA -i "$interface" -d 169.254.0.0/16 -j DROP
    fi
    if ! ip6tables -w -C FORWARD -i "$interface" -d fe80::/10 -j DROP 2>/dev/null; then
        ip6tables -w -I FORWARD 1 -i "$interface" -d fe80::/10 -j DROP
    fi
done
if ! iptables -w -C DOCKER-USER -j ROS-METADATA 2>/dev/null; then
    iptables -w -I DOCKER-USER 1 -j ROS-METADATA
fi
echo 'Container link-local denial installed; live deny probes are still required.'
