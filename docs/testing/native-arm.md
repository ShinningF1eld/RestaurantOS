# Native ARM S1 verification

The optional workflow `.github/workflows/s1-native-arm.yml` uses the GitHub
standard `ubuntu-24.04-arm` runner. It fails unless both the host and Docker
engine report ARM64 (`aarch64`/`arm64`); it installs no QEMU or cross-build emulator.
It installs only the committed Python/npm locks and Chromium, runs the shared image gate,
then runs the disposable HTTPS gateway matrix. API/worker use the same locally
built image identity and the browser matrix proves a real durable worker effect.
No registry push, deployment, production credentials or application migrations
are involved. Unique test databases and gateway volumes are removed by the
existing guarded runners.

The workflow runs on pushes to `codex/m9-s1-native-arm` and supports manual
dispatch after the workflow exists on the default branch. Publishing a branch
and starting remote CI require the user's authorization. Creating this file is
preparation, not a successful native run. Check repository visibility, runner
availability and account usage before authorizing a run; this guide makes no
claim about billing or available quota.

Retained artifacts contain the exact Git revision, host/engine architecture,
safe browser case status, limitations and verified cleanup. Private profiles,
runtime configuration, passwords and cookies are excluded. Record the actual
run URL, source revision and artifact outcomes in S1 evidence after the run;
emulated ARM results and an unexecuted workflow do not meet the native criterion.
The existing ten-gate CI and required `Milestone 6 acceptance` remain unchanged.

References: [GitHub runner labels](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
and [manual dispatch requirements](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
