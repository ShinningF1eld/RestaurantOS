# While you were away: from tested containers toward real servers

This is your learning journal, separate from the technical contracts and
runbooks. Date: 2026-10-28, Asia/Bangkok. Read this first; use the linked runbook
when you actually operate a host.

## What happened

I read the Milestone 9 design and the current implementation, checked the clean
branch and its dated test evidence, then merged S1 through
[PR #56](https://github.com/ShinningF1eld/RestaurantOS/pull/56). Main now includes
the native ARM checks and the container/HTTPS work. The merge commit is
`0410d3a3733ccc20ebf23f32fd6eef83a58d921a`.

I then started `codex/m9-s2-host-security`. The Oracle console opened at **Cloud
Sign In**, and the machine had neither an OCI CLI command nor a configured OCI
profile. That means I could prepare and test the work, but could not establish
your tenancy, free allowance, eligible image or actual host capacity. No VM,
cloud firewall, deployment key, application secret or application database was
created or changed by the S2 work. S2 remains incomplete.

The useful deliverable is a guarded preparation path: an inventory checker,
reviewable cloud-init files, small host scripts, tests, and the
[OCI host runbook](../docs/runbooks/oci-hosts.md). The example deliberately cannot
pass validation. Filling placeholders with guesses would defeat its purpose.

## The new boundary: your machine versus your server

S1 proved that the application can run through a container gateway on ARM. S2
asks whether we can operate the **machine around it** safely. A container test
does not tell us who can SSH into a VM, whether a database port is reachable
from the internet, or whether a reboot restores the right firewall rules.

Think of the layers as a series of questions:

| Layer | Question it answers | What does not answer it |
|---|---|---|
| OCI account | Will these exact resources remain inside the free allowance? | A trial-credit balance or a public pricing example |
| OCI network | Which outside machines can reach the host? | A container's internal port list |
| Linux/SSH | Who can administer the host, and how can we recover access? | An application login |
| Docker | Which container paths and ports exist, and which packets are forwarded? | UFW settings alone |
| Application | Which tenant and operations can this authenticated user access? | A secure SSH setup |

Each layer matters, and evidence from one does not automatically prove another.
This is why a green test suite still leaves real provisioning checks to do.

## Why the inventory is deliberately strict

An inventory is a small record of what we intend to build. Here it specifies
the home region, exact image ID, administrator public key/source address, isolated
networks and the two approved sizes. The checker rejects other shapes, extra
capacity, broad SSH access, overlapping networks and unreviewed eligibility.

The approved hosts together consume two OCPUs and 12 GB of RAM. If you already
have A1 machines using part of that allowance, adding both new machines can
exceed the budget. The script forces that fact into the conversation before
anything is provisioned. It cannot see your bill: the console review is still
required, including storage and ancillary resources.

One detail to recognize: `/32` means one IPv4 address. Allowing SSH from your
current public `/32` is much narrower than `0.0.0.0/0`, which includes the whole
internet. If your ISP changes your address, the narrow rule needs an intentional
update through your trusted recovery path.

The key validator checks the encoded structure of an Ed25519 **public** key.
It rejects private keys and extra `authorized_keys` options. A syntactically
valid public key still does not prove that you own its private half, so a fresh
SSH login remains part of acceptance.

## Cloud-init is a first-boot recipe, not a deployment pipeline

Cloud-init reads user-data when a VM is initialized. Our generated recipe
creates a named administrator, a disabled deployment account and private root
directories. It places reviewed scripts on disk but does not execute them or
start RestaurantOS. There are no database passwords or signing keys inside it.

This separation lets us inspect the host before tightening access. The recipe
keeps Ubuntu's bootstrap user temporarily. After the named administrator works
in a second session and console recovery is confirmed, the SSH hardening script
limits access to that administrator. Then we prove another fresh login before
closing existing sessions. A file saying the right thing is less useful than
actually demonstrating that we can still get in.

The generated SHA-256 hashes identify the exact bytes reviewed. Change a template
and the hash changes. A hash does not tell us that someone approved those bytes,
or that the running server received them. Later release controls must add that
identity and authorization evidence.

## Why deployment access remains disabled

The human administrator can use sudo because administering the host requires
that power. A CI deployment identity should have a much smaller vocabulary.
Docker access is effectively host-root access: someone who can start arbitrary
containers can mount host files or reach the Docker socket.

For now, `ros-deploy` has no key, no sudo, no Docker group and a `nologin` shell.
That is intentional. Giving it Docker access now and promising to restrict it
later would leave a powerful unattended path in the meantime. S5 needs to build
and test the exact-release wrapper before that identity can do useful work.

## Two networking surprises to remember

First, Docker-published ports can bypass the path UFW normally filters. So
“UFW blocks PostgreSQL” is not enough if Compose publishes PostgreSQL publicly.
We need the cloud rules, actual container bindings, Linux/Docker rules and an
outside connection attempt to agree.

Second, cloud hosts have a metadata service that software can use to learn about
the instance and, in some configurations, obtain workload credentials. Application
containers do not need that access. The staged guard denies link-local traffic
from ordinary Docker bridges without flushing platform-managed chains.

Finding the rule in a list is only a preliminary check. We still need a real
denied request, repeated after Docker restart and host reboot. A rule that
vanishes at boot is a temporary condition, not a reliable security boundary.
The guard is deliberately narrow; complete egress control remains more work.

## What the tests teach us

The regressions target mistakes with consequences: treating a string `"true"`
as console verification, accepting a boolean as a CPU count, selecting an image
from another region, opening SSH to the world, injecting key options, or
overwriting an existing reviewed bundle. These are cases where permissive input
handling can turn a small typo into a different infrastructure decision.

The first test attempts also exposed routine tooling issues: pytest needs to
run from the backend import context and needs writable temporary directories.
The secret scanner correctly flagged strings resembling private keys; those
specific negative-test fixtures are explicitly marked as synthetic false
positives. The scanner itself was not weakened.

Running the generated files through real Ubuntu cloud-init caught two subtler
issues. `sudo -l` can exit successfully while reporting that the account has no
privileges: a successful query is different from permission to execute a command.
The audit now recognizes the explicit denial and the regression attempts a real
noninteractive sudo command as the disabled user. Also, `sshd -T | grep -q` can
fail under `pipefail` if grep exits before sshd finishes writing. Capturing the
effective configuration first avoids treating that broken pipe as a bad policy.
These are good examples of why a plausible shell script benefits from execution
against the real tools.

Research also caught an identifier detail that a purely synthetic test missed:
OCI calls the home region `us-ashburn-1`, but older image identifiers contain
`iad`. The checker now handles the documented legacy spellings and has dedicated
regressions for them. Strict validation is useful only when its model matches
the real service; “reject everything unfamiliar” can become an operational bug.

Preparation tests prove that unsafe input is refused and review files have the
intended structure. They do not prove that OCI booted a machine or that an
outside attacker cannot reach a port. The technical verification document records
exact commands and their outcomes; keep that distinction when reading green
checks in future milestones.

## Where to pick up

Sign in to Oracle Cloud in the tab left open for you. Verify your home region,
account eligibility and existing resource usage. Do not paste passwords, private
keys or recovery codes into chat. The runbook walks through filling the ignored
inventory, reviewing the bundle, creating the testing host first, and collecting
the evidence needed before repeating on the application host.

When both hosts pass the live checks, we can close S2. Public HTTPS application
deployment is S3. Backups/recovery, restricted CI delivery and capacity acceptance
still have their own later slices. Getting a login page online would be progress,
but durable user data should wait for the recovery work to be proven.

The preparation is published in [draft PR #57](https://github.com/ShinningF1eld/RestaurantOS/pull/57).
The inventory unit suite now has 416 passing cases in total, including the rest
of the repository's unit tests. The [technical evidence](../docs/milestone9/verification-milestone9-s2-preparation.md)
keeps the exact commands, broader gate results and live checks still outstanding.
All ten shared local gates also passed, including the real database, browser,
image and migration rehearsals. The full run executed 414 unit cases before the
last region-name fix; the follow-up static/unit run passed 416. The evidence
keeps those observations separate so a later reader can tell which version was
actually checked. None of those checks migrated your application database.
GitHub then passed all ten gates on the final implementation commit `44ab07d`,
plus the separate Ubuntu bootstrap workflow. That gives us an independent check
on the supported Python 3.12/Linux setup, while the live cloud boundary remains
unverified.
