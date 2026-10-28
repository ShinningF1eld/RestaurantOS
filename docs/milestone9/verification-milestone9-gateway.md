# Milestone 9 S1 step #3: local Compose and HTTPS gateway

Verified: 2026-10-27 (Asia/Bangkok). Source starts at `35cc02a`; changes were
verified locally. The user authorized the local commit on 2026-10-28.
No cloud resources, public DNS, push or deployment.

## Scope and configuration

`deploy/local/compose.yaml` connects Caddy, Next.js, API, worker, PostgreSQL and
Redis, with an explicit maintenance tools profile. API/worker/maintenance share
the exact recorded backend image ID; frontend uses its recorded image ID.
Infrastructure images are pinned official manifest digests. Only Caddy publishes
loopback port 8443. Four bridges separate edge/frontend, edge/API, SSR/API and data
access. Both edge/API peers have fixed addresses and only Caddy's exact address
is trusted. Forwarded identity headers are replaced/removed at that edge;
Uvicorn rewriting remains disabled.

`scripts/local-gateway.py` generates private, ignored rehearsal state and fresh
secrets; refuses overwrites, redirected state, foreign project markers and any
DB target other than its own `postgres:5432/restaurantos_gateway_test`; serializes
operations; rejects migrations with live/paused/restarting writers; and requires
the actual DB revision to match the image before starting business services.
It rejects remote SSH/TCP Docker endpoints and refuses Compose operations before
both application image identities have been built and recorded.
Secrets are mounted at runtime. No secret is copied into image contexts or printed.

PostgreSQL and Caddy CA state use isolated persistent volumes. Normal shutdown
retains them. TLS verification uses the exported local root without installing
machine trust. No insecure-cookie setting or certificate-verification bypass.
API docs/schema stay closed at this gateway; slash redirects retain HTTPS/prefix.

The testing resource profile is applied and inspected: memory/PID ceilings,
CPU shares, bounded JSON logs, read-only application roots, Node heap, PostgreSQL
connection/shared-memory limits and Redis password/maxmemory/noeviction. API pool
settings explicitly support 5/0/5 in this stack; ordinary defaults remain 5/10/30,
and service-backed test mode retains NullPool. No schema/dependency/API-route change.

## Executed commands and results

Windows host uses Python 3.13.15/Node 24; runtime images use supported Python 3.12
and Node 24. Existing installed locks are used; installation was omitted.

| Command | Result |
|---|---|
| `backend/.venv/Scripts/python.exe scripts/local-gateway.py init` | Generated isolated project/config/secrets; no developer resources reused |
| `backend/.venv/Scripts/python.exe scripts/local-gateway.py build` | Both images built and exact identities recorded |
| `backend/.venv/Scripts/python.exe scripts/local-gateway.py migrate` | Explicit new rehearsal DB upgrade to `c3d8e1f52a74`; no application DB migration |
| `backend/.venv/Scripts/python.exe scripts/local-gateway.py up` | Six services started, actual schema/head match checked; public CA exported |
| `backend/.venv/Scripts/python.exe scripts/local-gateway.py check --restart` | Passed verified TLS/hostname, frontend/API routing, slash redirects, closed docs, cookies, CSRF, authenticated tenant/catalog creation, real protected SSR, durable worker receipt, spoofed-header allowance test, down/up persistence, memory/PID/exposure/network/pool/Redis checks |
| `backend/.venv/Scripts/python.exe scripts/local-gateway.py migrate` with live writers | Expected exit 1 before migration: running writers rejected |
| `backend/.venv/Scripts/python.exe scripts/local-gateway.py check` (final) | Passed including applied CPU/logging/read-only/PG-connection assertions |
| `./scripts/validate.ps1 -Gate baseline,backend-static,backend-unit,backend-integration,image -NoInstall` | Passed baseline/static, 347 unit, 342 integration, model-drift check and both AMD64 images with cleanup |
| `./scripts/validate.ps1 -Gate backend-static,backend-unit -NoInstall` | Final guard follow-up: static and 351 unit tests |
| `git diff --check` | Passed |

The initial network attempts caught two configuration mistakes: an automatically
allocated Docker /16 overlapped the first reserved /24, and dynamic API allocation
consumed the intended Caddy address. The initializer now selects a route-checked
10.240–249 /24 outside usual default pools, and both peers have explicit addresses.
The never-activated initial subnet was corrected while preserving generated
secrets. Later down/up checks retain the established address. A YAML flow-list
tmpfs quoting error was also corrected before successful migration/startup.
No workaround broadens proxy trust.

Two initial shared-gate attempts stopped at secret scanning of the deliberate
wrong-password literal, before backend tests. The test now derives a guaranteed
wrong value from the throwaway generated credential; the scanner passes without
a new baseline or suppression. Existing secret files are ignored and their ACLs
were inspected to confirm user/SYSTEM/admin/owner access only.

## Boundaries

This verifies local AMD64 container wiring and selected HTTPS/HTTP workflows,
not the complete step #4 Chromium/session/tenant/revocation/failure matrix.
No actual two-public-egress identity test, host reboot, new-head CI or cloud
capacity/recovery claim. Previous ARM64 image emulation evidence does not prove
these new Compose settings on a native ARM host. No host CA trust was installed.
No application database was migrated; no existing developer volume was deleted.

Frontend static/component/build/browser gates and the dedicated migration gate
are omitted in this task: no frontend code or schema changed. This is partial
validation, not full S1/M9 acceptance. Local PostgreSQL uses its bootstrap cluster
role; production DB-role hardening and release/backup/maintenance machinery remain
later work. Synthetic check records remain in this rehearsal only. See the
[operational/learning runbook](../runbooks/local-gateway.md).
