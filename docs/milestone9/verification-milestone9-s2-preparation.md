# Milestone 9 S2 preparation verification — 2026-10-28

Status: **partial implementation; S2 not complete**. The user authorized merging
S1, continuing S2 and committing/pushing/opening PRs while away. S1 merged through
[PR #56](https://github.com/ShinningF1eld/RestaurantOS/pull/56) at
`0410d3a3733ccc20ebf23f32fd6eef83a58d921a`. Its exact head `c3ef182` had passed all
ten shared gates and native ARM checks before merge; a new PR-triggered run was
also created. No required check or branch policy was bypassed or changed.

## Implemented scope

- `scripts/prepare-oci-hosts.py`: offline strict inventory validation, accepted
  resource split, recent explicit console review, resource headroom, home-region
  image ID structure, plain public key wire format, narrow administrator source,
  isolated VCN ranges, environment-specific cloud-init/network review files and
  hashes. It never invokes OCI/SSH or replaces a reviewed output directory.
- `deploy/oci/`: inert account/directory bootstrap, staged SSH hardening, official
  Ubuntu/Docker install, bounded daemon logs, additive container link-local rules,
  systemd guard and read-only local audit. Deployment account has no active key,
  shell/sudo/Docker permissions. No S5 release wrapper is activated prematurely.
- Synthetic Python regressions and a contained real Ubuntu/cloud-init/ShellCheck/
  OpenSSH regression. Both helpers are included in the existing static harness;
  the Ubuntu runtime regression is explicitly invoked separately.
- A separate read-only `S2 / synthetic Ubuntu bootstrap` workflow repeats that
  contained regression on relevant changes. No OCI/SSH/runtime secret or registry
  publisher permission is present; shared CI gates and aggregate are unchanged.
- [Host runbook](../runbooks/oci-hosts.md), current-state/roadmap alignment and a
  separate [learning journal](../../learning-journal/2026-10-28-m9-s2-while-you-were-away.md).

No business application code, API/schema, Alembic revision, dependency lock,
application database, runtime secret or production image was changed.
The roadmap now reflects the previously accepted self-hosted OCI/private-account
scope instead of managed database/resettable demo assumptions.

## Verification

| Exact command from root | Result |
|---|---|
| `./scripts/validate.ps1 -Gate @('baseline','backend-static','backend-unit') -NoInstall` | Passed: candidate secret scan, Compose/pip checks, Ruff/format/mypy and 414 unit cases; partial run only |
| `./scripts/validate.ps1 -Gate @('backend-static','backend-unit') -NoInstall` | Passed again after the documented legacy OCI region-ID correction: 416 unit cases and static checks |
| `docker run --rm --network none --mount type=bind,source=C:/Users/User/Documents/All_Projects/RestaurantOS/deploy/oci,target=/review,readonly python:3.12-slim bash -c 'set -e; for script in /review/*.sh; do bash -n "$script"; done; echo PASS:bash-syntax'` | Initial host scripts passed Bash syntax; later scripts covered by the Ubuntu regression |
| `backend/.venv/Scripts/python.exe scripts/check-oci-host-bundle.py` | Passed with a disposable Ubuntu 24.04 test toolchain; both schemas, ShellCheck, actual cloud-init modules, root/private ownership, inert deploy account, effective SSH policy and audit refusal on incomplete host |
| `docker build --tag restaurantos-oci-validation:local --file deploy/oci/validation.Dockerfile deploy/oci` followed by the same bundle checker | Passed against the tracked recipe, including explicit failure of deployment-identity audit after a synthetic accidental sudo grant |
| `./scripts/validate.ps1` | Passed all ten gates with committed-lock installation: baseline, backend/frontend static, 414 unit cases, 347 PostgreSQL cases, 10 client/19 component cases, frontend build, clean/legacy migrations, 29 host browser journeys, 15 HTTPS cases, both intentional-failure cleanup probes and both production images; disposable infrastructure removed |

The full command began before the later OCI region-alias correction and executed
414 unit cases. The final checker source separately passes static and 416 unit
cases, and the latest shell changes pass the contained Ubuntu regression. This
is cumulative local evidence across the working session, not an exact-final-SHA
full-run claim. Remote CI checks the published head separately. Logs that say
`FAIL` for the two intentional browser probes are required negative controls:
their expected failure and owned cleanup are verified by the passing parent gate.
Existing dependency warnings and canceled Next.js stream diagnostics remain;
there was no unexpected test failure in the successful full invocation.

The first toolchain image was built from an ignored Dockerfile with the same
official Ubuntu packages; the final passing run uses the tracked
`deploy/oci/validation.Dockerfile`. Its image ID is
`sha256:006d056bb22a3a53e8494c90822c5f3de8ef8859fe513cd77122ea146c7a3dae`;
cloud-init is `26.2-0ubuntu1~24.04.2`, ShellCheck `0.9.0`, architecture `x86_64`.
Test containers have no network, Docker socket or
extra capabilities; input mounts are read-only and generated fixtures are
synthetic. Containers/temporary fixture directories are removed. This is x86-64
Linux configuration evidence, not native ARM host runtime evidence.

Earlier attempts are not passing evidence: a root-directory pytest invocation
could not resolve backend imports; a sandboxed retry could not create temporary
directories; the secret scan flagged two synthetic malformed-key fixtures; static
checks caught implicit timezone use and inconsistent exception typing. These
were corrected and the shared gates rerun. The first real Ubuntu test caught
`sudo -l` returning zero even with a no-privileges result; a second caught a
`pipefail`/early grep exit false rejection of `sshd -T`. Both have corrected
handling and passing real-tool regressions. SSH service reload intentionally
fails inside the test container without systemd PID 1; it is not reported as a
successful reload. Actual Docker installation and privileged firewall mutation
are deliberately outside this contained regression.

## Outstanding live S2 evidence

OCI opened at Cloud Sign In, and neither an OCI CLI nor a configured local OCI
profile was available. No actual tenancy, host, network, image eligibility or
capacity was inspected. No cloud resource or access grant was created. Sign-in
and current tenancy facts are required before provisioning can proceed.

Both hosts still need the complete [runbook acceptance observations](../runbooks/oci-hosts.md#5-evidence-needed-before-declaring-s2-complete):
actual free allowance/image review, admin/console recovery and denial checks,
guest/OCI firewall and external port probes, live container metadata denial,
DNS/HTTPS continuity, restart/reboot persistence, storage identity/permissions,
and rebuild inventory. Egress rules/journal limits need actual host configuration
and verification. Cross-environment credentials/routes must be inspected live.

Restricted CI access, exact-release verbs and deployment startup checkpoints
remain later S3/S5 work. The prepared deployment user remains inaccessible.
No hosted environment, complete S2 or full M9 acceptance is claimed.

Published preparation: [draft PR #57](https://github.com/ShinningF1eld/RestaurantOS/pull/57).

## Published-source verification

At `44ab07d77b0738e122c39b1b083dd3ff2de0fa61`, both the push and PR runs passed
all ten shared gates and the unchanged `Milestone 6 acceptance` aggregate.
The [PR CI run](https://github.com/ShinningF1eld/RestaurantOS/actions/runs/40661751023)
checks the final code, including the 416-case unit suite. The independent
[synthetic Ubuntu workflow](https://github.com/ShinningF1eld/RestaurantOS/actions/runs/40661750994)
also passed. This supplies exact published-code evidence on Python 3.12/Linux
in addition to the local Windows Python 3.13.15 observations. Node is 24.
The follow-up documentation commit records these outcomes; it does not change
the verified implementation. Live OCI and native ARM host/reboot evidence remain
open; a green configuration workflow does not satisfy those criteria.
