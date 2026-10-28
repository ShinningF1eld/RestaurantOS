# Milestone 9 S1 closure checks — 2026-10-28

S1 is not yet accepted. Native ARM execution and exact-commit remote CI
remain pending. All ten local gates passed across the recorded corrective runs,
including complete affected-gate reruns for the final pool-ownership safeguard.
The available local Docker engine is x86-64, and the user
confirmed that no native ARM machine/runner is available. An unexecuted workflow
and earlier emulated results cannot establish native runtime compatibility.

Local results were recorded from the working tree above `7026352`. On
2026-10-28 the user authorized committing this S1 work and publishing the
`codex/m9-s1-native-arm` verification branch. This does not authorize later cloud
provisioning or deployment.

## Implementation

- Public `GET /ready` performs only `SELECT 1` through the existing API pool,
  with a two-second acquisition/query/return budget and generic uncached 200/503.
  `/health` remains process liveness. Deadline cleanup terminates an acquired
  asyncpg connection before cancelling the task, preventing a suspended database
  from extending graceful close. It first checks that the probe still owns an
  open lease, so a connection returned to the pool and borrowed by another request
  cannot be terminated. No schema or dependency changes.
- Gateway Compose uses readiness for API startup health; explicit schema checks
  and manually invoked migrations remain separate. See the
  [health contract](../api/health.md).
- Real integration regressions cover success, unavailable PostgreSQL, pool
  contention and cancellation. The HTTPS matrix suspends only its own database,
  proves bounded failure alongside live `/health`, resumes it and checks recovery.
  Teardown resumes a suspended owned database before removing it.
- Each gateway run now reuses the applied network/exposure/resource/pool checks,
  verifies API/worker image identity and image architecture against the engine,
  and retains safe image IDs and host/engine architecture observations.
- Browser history/profile checks retain actual BFCache observations separately
  from a controlled persisted-pageshow identity-switch check of the production
  restoration handler. No frontend product code or cache policy changed.
- The [native ARM workflow](../testing/native-arm.md) requires a native ARM host
  and engine, builds/runs both images and the real HTTPS/API/worker matrix, and
  retains only safe architecture/status/cleanup evidence. The existing required
  ten-gate CI is unchanged. Remote results remain pending publication/CI.

## Local verification

The earlier standalone HTTPS matrix passed all 15 cases and verified owned
resource removal. Its [sanitized evidence](evidence/s1-local-2026-10-28.json)
records a 2,017 ms stalled-database response, a real HTTP 404 document reload
under the switched identity, no former tenant marker, both controlled-peer
quota runs, persistent session/data/CA identity and exactly one durable worker
effect. Actual natural BFCache persisted-event count remained zero; Chromium
reported delegate/no-store/cookie-modification reasons. This does not claim
natural restoration occurred.

The final rebuilt images with the ownership guard also pass all 15 HTTPS cases
inside the complete browser gate. Their stalled-database response was 2,013 ms,
the switched-identity document reload returned 404, and both normal/failure
teardown were verified. The JSON's `browser_gate_gateway` records this final run.

The resource assertions are shared through read-only `check_runtime`; the
browser runner does not repeat the separate rehearsal helper's account smoke
test before starting its complete browser authentication matrix.

Commands from the repository root (all databases/services are disposable):

| Command | Current outcome |
|---|---|
| `./scripts/validate.ps1` | Installed committed locks; baseline/static/unit passed; integration failed as detailed below; subsequent gates were not reached in that invocation |
| `./scripts/validate.ps1 -Gate @('frontend-tests','frontend-build','migrations','image') -NoInstall` | Passed: 10 client and 19 component tests, production build, clean/legacy/backup/restore/downgrade migration checks and both application images |
| `./scripts/validate.ps1 -Gate @('baseline','backend-static','frontend-static') -NoInstall` | Passed over updated code, runner, workflow and documentation; Ruff/mypy/ESLint/Prettier/TypeScript and secret baseline |
| `./scripts/validate.ps1 -Gate backend-integration -NoInstall` | Passed: all 346 cases, no schema drift; owned infrastructure removed |
| `./scripts/validate.ps1 -Gate browser -NoInstall` | Passed final rerun: 29 host journeys, all 15 HTTPS cases, host intentional-failure cleanup and gateway intentional-failure cleanup; owned infrastructure removed |
| `./scripts/validate.ps1 -Gate @('backend-unit','backend-static') -NoInstall` | Passed again after final helper/diagnostic changes: 369 unit tests and backend static checks |
| `./scripts/validate.ps1 -Gate @('baseline','frontend-static') -NoInstall` | Passed again with sanitized evidence and final browser-script syntax/formatting |
| `./scripts/validate.ps1 -Gate @('backend-unit','backend-static','backend-integration') -NoInstall` | Passed with the final ownership safeguard: 369 unit tests, static checks, all 347 integration cases, no model drift and owned cleanup |
| `./scripts/validate.ps1 -Gate @('image','browser') -NoInstall` | Passed rebuilt ownership-safe images and the complete browser gate: 29 host journeys, 15 HTTPS cases and both verified failure-cleanup probes |

The local test interpreter is Python 3.13.15; production images and prepared
remote CI use Python 3.12. Node is 24. No lock was changed. Partial invocations
report their omissions; they are not individually full milestone acceptance.

Targeted readiness tests initially passed four cases against a fresh migrated
PostgreSQL database. Later real suspension tests exposed excessive graceful
cancellation time; after the cleanup correction, observed HTTPS 503 durations
were approximately 2.02 seconds and recovery passed.

The first full validation installed committed locks and passed baseline, both
static gates and 369 unit tests. Its integration route-authentication sweep
treated the newly public `/ready` as a business endpoint; the exact path has
since been exempted. That run finished with 345 passes, one failed test and one
fixture teardown error: the existing Redis key-cleanup command exceeded its
unchanged operation deadline. The initial full command is not a passing full
validation. The first corrected integration selection passed all 346 tests and
model-drift inspection. The final ownership regression raises that to 347 passes.
All ten local gates now have current passing results, without omitting a gate or
changing locks. This is cumulative local evidence, not a successful first full
command or an exact-commit remote CI result.

## S1 checkpoint mapping

| Requirement | Current evidence and boundary |
|---|---|
| R2 images/runtime | Both locked non-root application images pass smoke/content checks; gateway verifies actual API/worker image identity and engine/image architecture. Native ARM runtime is pending. |
| R3 local isolation | Applied networks, only loopback Caddy publication, fixed trusted proxy peer, private runtime configuration and resource settings are checked on the disposable stack. External exposure is S3 evidence. |
| R4 gateway sessions | Cookies, CSRF, actual access expiry, serialized renewal, uncertain refresh handling and distinct controlled-peer quotas/header forgery pass, repeated across restart. Public egress proof is S3. |
| R5 tenant/session isolation | API/HTML/RSC/navigation, warm permission revocation, account/history/profile changes and controlled persisted-pageshow reauthorization pass. Natural BFCache restoration remains unobserved with explicit reasons. |
| Base R10 | Bounded database readiness fails safely during suspension and recovers, while liveness stays healthy; session/data/CA and exactly-once durable worker effect survive down/up. Host reboot/recovery are later checkpoints. |
| Base R13 | Applied memory/PID/CPU/log limits, DB connection/pool budgets and Redis noeviction bounds pass. Capacity/OOM/full-memory/host operations remain S4/S6 work. |

The final full browser-gate retry also passed after read-only runtime inspection
was separated from the rehearsal account-smoke helper. An earlier gate attempt
passed host journeys and cleanup but failed before producing a gateway browser
report; its cleanup succeeded and its cause was not established. The retained
failure ledger does not relabel that attempt as a pass.

## Retained failure history

Final review identified a pool handoff race: a probe task may be delayed after
its connection is returned to the pool. Timeout termination now checks the
original SQLAlchemy lease is still open. A real PostgreSQL regression holds the
probe after return, lends that exact driver connection to another operation,
waits for the probe timeout and requires the borrower's `SELECT 42` to succeed.
An in-memory copy with only the ownership guard removed fails with a closed
borrower connection; guarded tracked code passes all six readiness/health cases.
No tracked source was altered for that negative control. The first negative
fixture accidentally held the borrower's cleanup too; it was interrupted, its
exact disposable project was removed, and the hook was restricted to the probe
before repeating the control successfully. The complete affected backend,
image and browser gates subsequently passed with the safeguard.

The initial stalled-database browser check failed before forced connection
termination was added. Teardown then exposed Docker's rejection of unpausing an
already running container. Cleanup now inspects the owned database's actual pause
state. Both affected disposable projects were subsequently removed using the
guarded cleanup and verified absent; their cleanup markers were written only
after that recovery.

An early browser startup failed while locked npm installation was in progress;
it produced no browser report. Subsequent restoration-test attempts failed before
the handler case was separated from the natural history/profile journey. These
are failed attempts, not acceptance results. One controlled restoration assertion
also incorrectly required HTTP 404 for Next's streamed not-found response. The
installed Next.js documentation confirms that response may be HTTP 200; the
check now requires an actual HTTP document reload, scoped not-found UI and no
previous tenant marker. A later diagnostic showed the earlier navigation wait
could resolve to Next's same-document history event with a null response, before
the reload. The wait now requires the actual main-frame document request.
API foreign-resource checks still require 404.

No global TLS bypass, lowered auth
quota, mocked authorization, application migration or developer-volume deletion
was used to obtain a pass.

## Remaining acceptance boundaries

Native ARM run URL, exact source revision, successful runtime jobs and sanitized
artifacts are required before marking native verification complete. Repository
instructions require fresh authorization before committing/publishing this work.
Natural BFCache restoration must be reported according to actual browser events;
a controlled event is not evidence that Chromium cached and restored a document.
Public TLS, two public egress clients, host reboot, cloud capacity and hosted
recovery belong to later S3/S4/S6 checkpoints and are not inferred from local S1.
