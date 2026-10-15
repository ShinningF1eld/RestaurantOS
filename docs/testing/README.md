# Testing strategy and quality gates

Supported baselines: Python 3.12, Node.js 24, PostgreSQL 16, and Redis 7.
Use Docker Desktop/Compose v2 and install Chromium once with
`cd frontend; npx playwright install chromium` after `npm ci`.

## One full local command

From the repository root on Windows:

```powershell
./scripts/validate.ps1
```

Linux/macOS use `backend/.venv/bin/python scripts/validate.py`.
Create the Python virtual environment first. Full validation installs the committed
hash-checked Python lock and npm lock without updating either, then runs all gates.
It provisions an independent Compose project with random loopback host ports,
healthy PostgreSQL/Redis, no developer volumes, and finally removes its resources.
Each database suite allocates a guarded unique database and drops it even on failure.
Browser and production frontend builds use temporary source copies.

An alternate Python 3.12 test environment can be selected with
`./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe`.
This selects an interpreter without skipping gates or changing the developer venv.

Individual gates use `./scripts/validate.ps1 -Gate backend-unit -NoInstall` or
`python scripts/validate.py --gate backend-unit --no-install`. These are explicitly
partial runs: omitted gates and installation are reported, and success never claims
full acceptance. The legacy `-Skip*` switches also select partial validation.
External CI services require explicit `TEST_DATABASE_URL` and use
`--external-services`; the configured database is a template, never a migration target.

Redis service runs require explicit `TEST_REDIS_HOST/PORT`. Local validation
discovers random loopback ports; external CI supplies its service ports. The
runner overrides ambient `REDIS_URL`, passes a 100 ms total budget and unique
test namespace into browser/API processes. Pure unit tests require no services.

## Shared local and CI gates

| Gate | Evidence |
|---|---|
| baseline | Compose configuration, dependency integrity, reviewed-baseline secret scan |
| backend-static | Ruff lint, separate Ruff format check, mypy |
| frontend-static | ESLint, separate Prettier format check, TypeScript |
| backend-unit | Service variables absent; pure policies/calculations/orchestration |
| backend-integration | Real migrated PostgreSQL, API authentication/tenancy, model drift; async Redis commands, deadline, outage liveness and owned cleanup on success/failure |
| frontend-tests | Components and real API transport with isolated browser/network mocks |
| frontend-build | Production Next.js build in an isolated source copy |
| migrations | Clean and seeded legacy upgrades, preservation and downgrade guards |
| browser | Real Chromium/API/PostgreSQL, production frontend, isolated processes/ports |
| image | Locked Python production image, content inspection, startup and cleanup |

CI runs the same portable runner per matrix gate on Python 3.12 and Node 24.
The matrix does not stop remaining gates after one failure. Its aggregate
`Milestone 6 acceptance` job uses `always()` and fails unless the entire matrix
succeeds. Push, pull-request and merge-group events have no path filters.
Partial per-job execution is intentional; the aggregate requires the complete set.
Local Windows uses junctions for isolated frontend dependencies; Linux uses symlinks.

## Layer ownership and regression maps

- [Dependencies and format checks](dependencies.md)
- [Backend test boundaries and critical-rule map](backend.md)
- [Frontend component/client tests](frontend.md)
- [Browser journey matrix](browser.md)
- [Migration baseline and preservation](migrations.md)
- [Milestone 7 menu-read benchmark](menu-read-benchmark.md)
- [Coverage feedback and exclusions](coverage.md)
- [Backend image build and smoke checks](image.md)
- [Required-check policy and administrator governance](enforcement.md)
- [Dated Milestone 6 acceptance review](../milestone6/milestone-6-verification.md)

Prefer filling a demonstrated critical-behavior gap over duplicating existing
tests or raising counts. Issue #34 adds worker unit tests and real-process
PostgreSQL/Redis integration coverage for relay claiming/fencing, group routing,
crash windows, ambiguous publication, pending reclaim, stream loss, outage
recovery and bounded backlog. Run them through `backend-unit` and
`backend-integration`; issue evidence is in
`docs/milestone8/verification-milestone8-issue34.md`. T5 adds
`unit/test_event_execution.py` and `integration/test_event_execution.py` for
atomic effect/receipt transactions, overlapping duplicates, process death before
commit/ACK, eight-attempt poison isolation, due times across restarts, shared
outages, real PostgreSQL connection termination, safe CLI inspection and replay.
T6 adds `unit/test_analytics_projection.py` and
`integration/test_analytics_projection.py` for the actual analytics handler:
creation-date decimal totals, scope reconciliation, deletion permutations,
lock-proven competing same/different-order effects, atomic rollback, queued
events after rebuild and real analytics worker death before/after commit. T7
adds `integration/test_alert_projection.py` for out-of-order episode history,
revision-fenced current state, baseline suppression, deduplicated durable stubs
  and diagnostics, preservation during rebuild, both stock-lock/stub-commit
  timing boundaries observed through PostgreSQL's wait graph, overlapping
  history deliveries, actual-effect rollback, and real alert/sink worker death
  before commit and after commit/before ACK. Transport-only tests explicitly
  disable feature handlers in test wiring; the production entrypoint test checks
  the real durable diagnostic effect. Earlier T5 tests use trusted code-only handlers with real
database effects. Redis continues to validate Milestone 7
caching/rate limiting independently.

T8 adds `integration/test_event_maintenance.py` for scoped legacy initialization,
truthful suppressed baselines, reruns after recovery/threshold/archive changes,
queued order watermarks, rollback and retained-record analytics reconstruction.
Concurrent initialization observes the shared restaurant lock through PostgreSQL.
The `migrations` gate restores a custom-format backup of seeded legacy data into
another disposable database, explicitly migrates it and exercises production
initialize/rerun/rebuild/reconcile CLI commands and retained-provenance downgrade
protection. Local runs use tools in the owned test PostgreSQL container; external
services require PostgreSQL 16 `pg_dump` and `pg_restore` on PATH. This rehearsal
does not connect to the application database or invoke business/worker processes.

## Failure and cleanup evidence

`python scripts/validate.py --gate backend-integration --no-install
--inject-failure backend-integration` deliberately fails after test services start.
The command must return nonzero and remove its Compose project. Migration and
browser runners also expose targeted failure injection for their own cleanup paths.
No cleanup selects the developer Compose project or deletes the configured database.

CI uploads available coverage and safe browser diagnostics on success and failure,
retaining artifacts for seven days. Authentication traces remain disabled because
they can embed passwords/cookies; screenshots and structured summaries provide
failure evidence without persisting those credentials.

Final execution results and enforcement evidence are recorded in the dated
[Milestone 6 verification](../milestone6/milestone-6-verification.md); historical counts are
not current acceptance.
