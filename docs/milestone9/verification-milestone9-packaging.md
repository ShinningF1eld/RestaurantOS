# Milestone 9 S1: application image preparation

Date: 2026-10-27 (Asia/Bangkok). This records step #2 of the local S1 sequence,
above committed routing preparation `2fcca62`. Packaging changes were verified
locally. No push, release, provisioning or deployment was performed.

## Scope

- Backend dependency/runtime stages retain the existing pinned Python 3.12 base,
  hash-locked dependencies and non-root runtime. Binary wheels are required;
  the runtime receives installed dependencies, application and Alembic files.
- API explicitly disables Uvicorn forwarded-header rewriting. Worker uses the
  same image with `python -m app.worker` and its API healthcheck disabled by the
  caller. Packaging checks import that entrypoint; this is not worker-progress
  evidence. Startup never runs migrations.
- Frontend uses pinned Node 24, locked `npm ci`, standalone output and copied
  public/static assets. Browser API base is fixed to `/backend` during image
  build; private `API_URL` remains runtime configuration. Runtime is non-root.
- Image scripts inspect versions, users, contents, configuration and platforms.
  Frontend smoke checks static/dynamic pages, public assets, linked static assets
  and health with an unavailable API; backend checks health and disposable DB
  connectivity while proving startup creates no schema.
- Existing `image` gate requires both checkers. Required gate names, aggregate,
  workflow and repository rules are unchanged. Unit policy/cleanup regressions
  supplement the real smoke checks. Documentation describes commands and limits.

## Verification

Host tests used existing installed dependencies: Python 3.13.15 and Node 24;
supported backend CI/runtime remains Python 3.12. No dependency versions or locks
changed. Docker Desktop was initially stopped and was started for these checks.
All service-backed work uses owned disposable projects/databases, not the
developer application database or its volumes.

| Command | Result |
|---|---|
| `./scripts/validate.ps1 -Gate backend-static,backend-unit,frontend-static,frontend-tests,frontend-build -NoInstall` | Passed before the five new image policy/cleanup cases; 329 unit tests, frontend component/client suites and standalone production build |
| `./scripts/validate.ps1 -Gate backend-static,backend-unit,backend-integration,browser -NoInstall` | Passed updated static, 334 unit tests, 342 integration tests, Alembic model-drift check, 29 Chromium workflows and intentional browser-failure cleanup probe |
| `./scripts/validate.ps1 -Gate baseline -NoInstall` | Passed dependency integrity, Compose configuration and candidate-file secret scan |
| `./scripts/validate.ps1 -Gate image -NoInstall` | Passed both AMD64 images, content/user/runtime/assets checks, disposable DB/no-migration smoke and cleanup |
| `backend/.venv/Scripts/python.exe scripts/check-frontend-image.py --inject-failure-after healthy` | Expected exit 1 after successful smoke; exact-name container absence verified afterward |
| Changed-file Ruff lint/format and `git diff --check` | Passed |

The first focused validation-policy invocation inside the Windows sandbox had
five temporary-directory fixture errors (12 passed); the full updated unit gate
outside the sandbox passed all 334 cases. Earlier sandbox asyncio/socket-pair
limits are recorded in current-state evidence. Gates above ran outside it.

Both pinned official base manifest indexes advertise AMD64 and ARM64:

- Python: `sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`
- Node: `sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205`

ARM64 build/run verification passed under Docker Desktop emulation, using
`build_image('restaurantos-backend:m9-arm64', 'linux/arm64')`, matching
`inspect_image`, and `run_smoke(image, 90, None, owned_postgres_container)` in a
separate `validate.services(False)` disposable context. The frontend command was
equivalent to `scripts/check-frontend-image.py --image restaurantos-frontend:m9-arm64 --platform linux/arm64 --timeout 90`.
Both contexts removed their owned containers/networks/databases afterward.

| Inspected image | Architecture | Image ID | Reported bytes |
|---|---|---|---|
| `restaurantos-backend:m6` | AMD64 | `sha256:5c1950c23ffc6293190b9004e179628af74a4ccc8c78aa8c757b73f85b1dbd04` | 60628513 |
| `restaurantos-backend:m9-arm64` | ARM64 | `sha256:1a2bdc44de14ec4b9721daa7f4c4a827333d10110319b223cfd004f3fe92cc54` | 62372212 |
| `restaurantos-frontend:m9` (cleanup probe build) | AMD64 | `sha256:9a98563476145f6a1144278407e4b8d559379db5d8d914abb390edbafab002c7` | 93304329 |
| `restaurantos-frontend:m9-arm64` | ARM64 | `sha256:3c901407b8edea9e1f4c95d5d95105d60f60e8fd72c211255c13a081ab64d732` | 93438410 |

Native ARM/OCI runtime and capacity are unverified; emulation cannot establish
those claims. Reported image sizes are inspection values, not a comparison
against the old image or a capacity measurement.

The existing browser harness still uses `next start`, which emits a standalone
configuration warning. Its 29 workflows passed; those are host-server behavior
regressions, not proof of the standalone container entrypoint. Both image smoke
checks execute the documented `node server.js` entrypoint. Browser output also
includes existing color-environment, cancelled-stream and expected scoped-404
diagnostics; backend tests retain the existing Starlette/naive-UTC deprecations.

## Remaining boundaries

This is partial validation with locked installation omitted, not full milestone
acceptance. The dedicated migration gate is omitted because there is no schema
change. No application migration was performed. No public API contract, business
behavior, dependency, database schema or production workflow changed in step #2.
New-head CI/remote required-check proof was not run or published.

Compose/Caddy wiring, HTTPS cookies, forwarded client identity, real worker
effects through the container stack, hosted SSR/tenant isolation and host-level
resource/capacity/recovery evidence remain subsequent S1/M9 work. This report
does not mark S1 or M9 complete.
