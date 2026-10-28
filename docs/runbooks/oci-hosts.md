# OCI host preparation (Milestone 9 S2)

Status: repository preparation only, 2026-10-28. **No OCI host has been created
or verified by this work.** Console authentication is the immediate dependency.
S1 was merged through [PR #56](https://github.com/ShinningF1eld/RestaurantOS/pull/56).
The user's current S2 implementation instruction supersedes the design's historic
design-only task restriction; it does not authorize paid substitutes.

This runbook applies only to new dedicated Ubuntu 24.04 ARM64 hosts. Never run
the bootstrap against a developer machine, an existing data host, or a restored
host with unknown configuration. Read the [design](../milestone9/milestone-9-design.md)
for the complete trust model. S2 does not activate a public application.

## 1. Verify the tenancy before rendering

In the authenticated OCI console, record the actual home region, active/trial
status, existing A1 allocations, boot/block storage (including retained volumes),
eligible Ubuntu ARM image OCID and availability. The proposed split is one
1-OCPU/8-GB/50-GB application VM and one 1-OCPU/4-GB/50-GB testing VM.

Oracle currently documents 1,500 A1 OCPU hours/9,000 GB hours monthly (equivalent
to two OCPUs/12 GB), 200 GB combined boot/block storage, home-region eligibility,
capacity shortages and idle reclamation. The inventory checks this conservative
allocation budget, not billing, ancillary charges, actual capacity or eligibility.
Check these in the console; trial credits do not establish an ongoing zero cost.
Stop for capacity exhaustion or any paid resource; do not upgrade automatically.
[Official allowance policy](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Keep private inventory and generated bundles in ignored `.local-oci/`, with a
protected off-machine copy. Do not commit resource OCIDs, public administrator
source IPs, host keys, account identifiers or credentials as evidence. The example
intentionally fails validation. It contains no valid account, image or SSH key.

```powershell
New-Item -ItemType Directory -Force .local-oci
Copy-Item deploy/oci/inventory.example.json .local-oci/inventory.json
# Edit the private copy with console-verified facts, not guesses.
backend/.venv/Scripts/python.exe scripts/prepare-oci-hosts.py .local-oci/inventory.json
backend/.venv/Scripts/python.exe scripts/prepare-oci-hosts.py .local-oci/inventory.json --output .local-oci/review-001
```

The review date is UTC, accepted for today or yesterday only. This forces a
recent operator assertion; it cannot prove that a console review happened.
Additional unknown fields are rejected, including accidental private-key fields.
Use one plain Ed25519 **public** key without its comment. The wire-format check
is not a proof of key possession. Keep the corresponding private key in the
operator's existing secure custody, outside cloud-init and Git.

Copy the exact image OCID, not its display name. OCI image identifiers use `phx`
and `iad` for the older Phoenix/Ashburn regions; the checker maps those to
`us-phoenix-1`/`us-ashburn-1` and rejects other region mismatches. This structural
check still cannot prove that the image exists, is ARM64, or is Always Free.
[Oracle's OCID format](https://docs.oracle.com/en-us/iaas/Content/General/Concepts/identifiers.htm)
and [Canonical's image lookup procedure](https://ubuntu.com/docs/oracle/oracle-how-to/find-ubuntu-images/).

Rendering is offline and creates a new directory, never overwriting a bundle.
Review both `*.cloud-config.yaml`, `network-plan.json` and `sha256.json`. Cloud-init
accepts this JSON document as YAML after the `#cloud-config` header. Re-render
after any template/inventory change and compare hashes. A hash identifies the
reviewed bytes; it is not a signature, approval, or proof of cloud installation.

## 2. Create isolated network and hosts manually

Use separate VCNs with non-overlapping ranges from the inventory; no peering,
cross-environment routes or shared database. Keep public IPv6 unassigned until
equivalent rules and external tests exist. Use only the necessary public IPv4
entrypoint and verify its current price/eligibility in the tenancy.

Before boot, configure stateful OCI ingress for TCP 22 from the administrator's
single public IPv4 `/32`. No CI range is authorized at this stage. Leave 80/443
closed until S3. Never expose 3000, 5432, 6379, 8000, 2375 or 2376. Inspect **all**
attached NSGs and subnet security lists: OCI allow rules combine, so a narrow NSG
does not cancel a broad security-list allow. Do not retain default world-open SSH.

Record resolver/time endpoints and required HTTPS package/registry/certificate
destinations; configure/verify egress under the design policy. The generated plan
does not install OCI ingress/egress or guest INPUT rules. Preserve image-provided
OCI networking/console recovery rules; inspect the actual guest firewall before
editing. A broad HTTPS allow is not proof of exfiltration prevention.

Create the testing VM first using its exact reviewed eligible image, shape,
memory/boot size and user-data file. Repeat for application only after testing
passes. Do not silently accept a larger/paid fallback or a different architecture.
Record the actual image/shape, allocated sizes, volume deletion policy and hash
of user-data in the private rebuild inventory. No application volume/data exists
in this bootstrap; do not transfer developer or rehearsal databases.

## 3. Prove administrator access before SSH hardening

Obtain host-key fingerprints through trusted OCI console access. Compare them
with the SSH server, then pin them in the operator's `known_hosts`. Do not trust
an unauthenticated network `ssh-keyscan` as the identity proof. Use strict host-key
checking for later connections. Rebuilds require a deliberate fingerprint change.

Wait for `sudo cloud-init status --wait`; inspect failures without publishing
user-data/logs. Cloud-init creates the named sudo administrator and a password-
locked `ros-deploy` account with `nologin`, no keys and no Docker/sudo grant.
It retains the image's default user during bootstrap to reduce lockout risk.
It disables password/root SSH via cloud-init and stages root-only host scripts.
It does not install packages or execute those scripts automatically.

Open a **second independent** SSH session as the named administrator. Verify
`sudo -n true` and trusted console recovery before running:

```bash
sudo bash /opt/restaurantos/bootstrap/harden-ssh.sh rosadmin --second-session-and-console-verified
```

Replace `rosadmin` with the actual inventory administrator. The flag is an
operator assertion, not automatic evidence. The script validates SSH syntax and
key effective settings before reload. `AllowUsers` then permits only this named
administrator, excluding the default user and disabled deployment user. It
disables SSH forwarding and tunnels; interactive admin SSH itself
continues to work. Keep existing sessions open and prove another fresh login
after reload. Do not edit a working key through an unverified session.

The script refuses to replace its prior hardening file. Later changes need a
trusted review with recovery access. Installer, templates and parent directories
are root-owned; applications/deployment accounts must never modify them.

## 4. Install Docker and stage network protection

On the fresh testing host, review the staged scripts, then explicitly invoke:

```bash
sudo bash /opt/restaurantos/bootstrap/install-docker.sh
sudo bash /opt/restaurantos/bootstrap/audit-host.sh rosadmin
```

The installer checks Ubuntu 24.04/aarch64 and the environment marker, refuses
existing/conflicting runtimes/configuration, and installs from Docker's signed
official Ubuntu apt repository. It records installed OS package versions in
root-only `/var/lib/restaurantos/host-packages.txt`; OS packages are selected from
the stable repository at installation time, not an application dependency lock.
For rebuild reproducibility retain those versions and verify their availability.
Application Python/npm locks are unchanged. Require Engine/CLI 28+ and Compose v2.
[Supported installation procedure](https://docs.docker.com/engine/install/ubuntu/).

An interrupted installation leaves state for trusted inspection. The installer
will refuse an automatic rerun once Docker/configuration exists; do not delete
that state blindly to bypass the check. Diagnose the failing apt/service step,
review the recorded changes and complete recovery deliberately.

The staged daemon configuration disables live restore and default-bridge IPv6,
and selects `json-file` logging with 10-MB files/three rotations. It does not set
global container restart policies, memory/PID limits or application startup. S3
must configure and inspect those for the actual release. Existing logs are not
rewritten. Add bounded journald storage during the host operations phase and
measure disk/inodes before installing images; retain at least 10 GiB free under
the design's stricter peak-space guard. Do not prune any volumes.

The network guard adds IPv4 link-local denial for `docker0`/`br-*` traffic through
`DOCKER-USER`, plus IPv6 link-local denial in `FORWARD`. It never flushes OCI,
Ubuntu or Docker chains. Its systemd unit starts after Docker and is attached
to Docker restart/boot. This is a narrow metadata defense, **not** the complete
egress/public-ingress firewall. Do not enable Docker's experimental nftables
backend with these iptables rules. Custom-named bridges, host networking,
macvlan/ipvlan, privileged containers and Docker socket mounts are prohibited.
Future release startup must require successful guard execution before launching
writers. S3/S5 still own the persisted maintenance/startup checkpoint; no current
script claims to solve interrupted migration boot races.

Docker-published ports can bypass UFW. Keep OCI filtering and inspect guest/Docker
rules; never infer external isolation from a green local audit alone.
[Docker firewall model](https://docs.docker.com/engine/network/packet-filtering-firewalls/).

`audit-host.sh` is read-only and emits fixed PASS/FAIL labels. Nonzero means at
least one missing local prerequisite. It checks the architecture/OS, SSH, private
paths, disabled deployment account, daemon defaults, service/guard state and a
TCP public-listener allowlist. Rule presence is not packet-denial proof; default
daemon settings are not inspection of individual containers. It does not dump
environment variables, keys, settings, OCI addresses or DSNs.

## 5. Evidence needed before declaring S2 complete

Retain private raw evidence and a sanitized dated summary, distinguishing testing
and application. Each host needs:

- Actual free-eligibility/resource/image review, successful cloud-init and a
  private rebuild inventory including host-key fingerprints and package versions.
- Fresh named-admin login, working sudo/console recovery; default/root/password
  and disabled deployment-user access denied. No Docker-group/sudo/socket access
  for `ros-deploy`; no deployment key or unrestricted wrapper installed.
- Actual guest/OCI rules and denied external TCP probes for every direct service
  and Docker API port, from an unauthorized source as well as an allowed admin.
  Confirm UDP/IPv6 exposure independently; the local audit covers TCP only.
- Real metadata denial from disposable containers on default and Compose bridges.
  Use an approved empty/synthetic probe; retain response status only, **never**
  metadata contents, instance credentials or tokens. Verify DNS/HTTPS still work
  and host platform services retain their required connectivity.
- Docker restart **and host reboot**, guard restoration, repeated deny probes and
  audit. No application writers may start; inspect actual container restart state.
- Private storage paths/ownership, no cross-environment credentials/routes, host
  patch/reboot procedures and disk/log limits. Separately verify container GIDs
  before provisioning runtime file secrets in S3.

The OCI access/sign-in dependency cannot be replaced by a fabricated console
assertion or by publishing a test inventory. Schema validation, syntax tests and
unit tests are preparation evidence only. S2's two-host exit criterion stays open
until these live observations exist. Restricted deployment verbs, per-host CI keys
and the exact-release wrapper remain disabled until S5 implements/verifies them.

## Repository regression commands

From the repository root with committed Python dependencies installed:

```powershell
./scripts/validate.ps1 -Gate @('baseline','backend-static','backend-unit') -NoInstall
docker build --tag restaurantos-oci-validation:local --file deploy/oci/validation.Dockerfile deploy/oci
backend/.venv/Scripts/python.exe scripts/check-oci-host-bundle.py
```

The optional Ubuntu toolchain image installs official Ubuntu test packages; it
is not an application/runtime image or a provisioned OCI OS. The checker creates
only a synthetic temporary bundle, then uses `docker run --rm --network none`
with read-only template/bundle mounts, no Docker socket and no extra privileges.
It validates both schemas, runs Bash syntax/ShellCheck, executes real cloud-init
account/directory/file modules, verifies SSH policy parsing and confirms that
missing Docker/systemd/firewall prerequisites make the audit fail.
The real SSH reload is expected to fail without systemd PID 1; this test never
reports it as a successful host reload. It does not execute the Docker installer
or exercise privileged packet rules. The image is retained for reruns; ordinary
containers and temporary fixture directories are removed. No application schema
or dependency lock changes are involved. Run the full shared gates for broader
repository acceptance; these preparation checks alone cannot close S2/M9.

The separate `S2 / synthetic Ubuntu bootstrap` workflow runs this container
regression for relevant file changes or manual dispatch, with only repository
read permission. It receives no OCI/SSH/runtime credentials, publishes no image
and provisions no infrastructure. The ten shared gates and required aggregate
are unchanged. It provides repeatable configuration evidence, not hosted proof.
