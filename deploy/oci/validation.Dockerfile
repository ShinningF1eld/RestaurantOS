# Test toolchain only; never an application or OCI host image.
FROM ubuntu:24.04
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        cloud-init shellcheck openssh-server sudo iptables \
    && rm -rf /var/lib/apt/lists/*
